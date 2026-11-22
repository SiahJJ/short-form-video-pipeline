# Running it unattended on a home PC: wake schedules, storage and notifications

The pipeline is a set of small scripts run by **Windows Task Scheduler**. There is no always-on server: the PC
can sleep, wakes itself for each job, stays awake only while work is happening, and tells you by email when
something needs you.

## 1. Waking up and running on schedule

### Work windows: on only when needed {#work-windows}
The first version let ~15 tasks wake the PC on their own timers (some every 5 minutes), so it effectively
never slept. Now **only one scheduler wakes the PC**:

| Window | When | What happens |
|---|---|---|
| Posting | 6 times a day, at the **best-performing hours** learned by the performance loop (for example 00, 09, 12, 15, 17, 20) | Instagram and Facebook post back to back (5–10 min gaps) for ~50 min; TikTok drafts are sent; YouTube uploads go out with scheduled `publishAt` so they go live at peak times even while the PC sleeps |
| Night | 02:30 | Discovery, downloads, clipping, metadata, cleanup, metrics + analysis; stays only while clipping/downloading is active (45 min – 4 h), then **re-plans tomorrow's posting hours** |

How it works:
- The window task runs through the stay-awake wrapper, writes a `work_window.json` flag with its end time,
  starts the pipeline's tasks immediately, waits, removes the flag, and exits. Windows then sleeps on its
  normal idle timer.
- The publishers read the flag. While a window is open they use the short burst gap, so a window's worth of
  posts fits inside it. The rolling 24 h caps still apply.
- Every other task keeps its schedule but has **"wake the computer" switched off**: it runs whenever the PC
  happens to be awake, and never wakes it.
- Result: roughly **8–9 hours awake per day instead of 24**.

### Task settings that matter
Every task is registered with the same settings ([`ops/register_task.ps1`](../ops/register_task.ps1)):

| Setting | Value | Why |
|---|---|---|
| **Wake the computer to run this task** (`WakeToRun`) | on | The PC can sleep; the timer wakes it for each run |
| **Run task as soon as possible after a scheduled start is missed** (`StartWhenAvailable`) | on | A run missed while the PC was off happens at next boot |
| **If the task is already running** (`MultipleInstances`) | `IgnoreNew` | A slow run (a long render) is never started twice |
| **Stop the task if it runs longer than** (`ExecutionTimeLimit`) | per task (2 min to 2 h) | A hung network call can't block the schedule forever |
| Repeat interval | 5 / 15 / 30 min, hourly, 4-hourly, weekly | Matched to how often each stage has new work |

Windows also has to allow wake timers. In **Power Options → Change advanced power settings → Sleep → Allow
wake timers**, choose **Enable** (on battery too, if you want it on a laptop). Check what can wake the PC with:

```bash
powercfg /waketimers
```

### Staying awake only while working
Waking is only half of it: Windows can fall back asleep in the middle of a 40-minute render. Long jobs run
through a tiny wrapper ([`ops/run_awake.py`](../ops/run_awake.py)) that calls
`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` for the job's lifetime, then releases it. The PC
then goes back to sleep on its normal idle timer. No power-plan changes and no "never sleep".

### Going back to sleep safely
Windows' idle timer turned out to be unreliable: a publisher that keeps looping between posts holds the PC
awake for hours. So every work window ends by starting a **safe-sleep** step that waits (up to 3 h) until:
- nobody has touched the keyboard or mouse for 15 minutes (it never sleeps under someone using the PC);
- no clipping job, download or encode is running;
- no upload is in flight: an Instagram publishing cycle that started but hasn't logged its exit code, the
  Facebook publisher's lock file, or the TikTok sender's task.

Then it calls `SetSuspendState`. If it never becomes safe, it leaves the PC alone, and the next wake timer
still fires either way.

### No pop-up windows
Console programs started by Task Scheduler normally flash a window and steal focus (a problem mid-game). Every
action goes through [`ops/run_hidden.vbs`](../ops/run_hidden.vbs):

```
wscript.exe //B //Nologo run_hidden.vbs "C:\path\to\python.exe" "C:\path\to\script.py" --apply
```

It starts the command with a hidden console that child processes (ffmpeg, node, powershell) inherit, waits for
it, and passes the exit code back to Task Scheduler, so the "Last Run Result" column stays meaningful.

### Self-healing
- **Watchdogs** restart the local servers (clipper API, OAuth/publisher, video server) if they stop answering.
- **Single-instance locks** (lock files with a staleness timeout) protect stages that also have manual entry
  points.
- **Readiness gates:** a publisher checks its dependencies (local servers answering, token valid) before
  doing anything, and does nothing rather than half a job.
- Restart-safe state: a job's result is saved to disk, so a crash or restart never causes re-work. Losing
  that guarantee once made a 4 GB video get clipped three times.

### Crash and reboot recovery
A power cut, a Windows Update restart or a blue screen can stop the pipeline at any point. The goal is that
it comes back on its own, with nothing posted twice and nothing left stuck.

**1. Something has to run after the restart.** This is the trap: a task set to *Run only when user is logged
on* does **not** run while the PC sits at the sign-in screen after a reboot. That includes the wake tasks that
start every work window. There are two ways out:

| Option | How | Trade-off |
|---|---|---|
| **Auto sign-in, then lock** (simplest) | Turn off *Settings → Accounts → Sign-in options → "Only allow Windows Hello sign-in"*, then set auto sign-in with Microsoft's Sysinternals **Autologon** (it stores the password as an encrypted LSA secret). Add an *At log on* task that runs `rundll32.exe user32.dll,LockWorkStation`. | Everything behaves exactly as it does after a normal sign-in: per-user tokens, tray apps, the local LLM. The PC boots to a locked desktop. |
| **Run whether logged on or not** (S4U) | Re-register tasks with `-LogonType S4U` (needs an admin shell). | No stored password, but S4U sessions have no user credentials. Secrets protected with **per-user DPAPI** may not decrypt until someone signs in, so token-based publishers can still fail. Use machine-scope protection or a vault if you go this way. |

Also:
- Run Tailscale in **unattended mode** (`tailscale set --unattended`) so Funnel/Serve stay up with nobody
  signed in. Otherwise the platforms can't fetch your video URLs.
- Give boot-critical servers an **At startup** trigger. Pick **active hours** in Windows Update so restarts
  happen outside work windows.

**2. A recovery pass** ([`ops/boot_recovery.py`](../ops/boot_recovery.py)) runs at sign-in **and at the
start of every work window**:

| Left behind by a crash | What recovery does |
|---|---|
| A work-window flag whose window died | Removes it, so publishers stop using short burst gaps |
| A render job record stuck at `running` | Asks the render server. If it doesn't know the job, marks it `error`, and the worker re-submits the source |
| A local server, the LLM or the tunnel not up | Starts its task again, or logs it |
| The nightly clipping window missed while the PC was off | Starts it now instead of waiting a day |
| An upload stopped mid-flight (`uploading` / `publishing`) | **Reports it only** |

**3. Never guess about uploads.** Each publisher writes its intent to the ledger *before* the request that
creates the post, and writes every ledger atomically (temp file plus rename). After a crash an item is in one
of three states: never started (safe to send), confirmed (done), or **in flight**. In-flight items are never
retried automatically, because the platform may already have the post. A human checks once and settles it.
This cost one stuck item in the first week. A double post would cost far more.

Testing it: plant a stale flag and a fake `running` job record, run the task, and check the log. Then
`python boot_recovery.py --check` should report everything up.

## 2. Keeping the disk from filling up

A 4K source can be 3–6 GB, and the pipeline briefly holds several copies of each video (download → clipper copy
→ render scratch → clips → platform-optimised copies). Five layers keep this bounded:

1. **Admission caps at download time:** no livestreams, at most 4 h, at most 6 GB, format tiers that prefer
   ≤1440p. Rejected sources get their own status so they aren't retried forever.
2. **A free-space floor:** downloads pause below 20 GB free, so the disk can never be driven to zero.
3. **Hard-link dedupe:** the clipper's copy and the original download become one file with two names
   ([`src/storage/dedupe.py`](../src/storage/dedupe.py)), halving source storage at no risk.
4. **The storage guardian, hourly** ([`src/storage/guardian.py`](../src/storage/guardian.py)): it deletes
   only what the pipeline provably no longer needs. Sources go 30 min to 2 h after clipping, scratch after
   3 h, and clips once every platform has confirmed them. It switches to shorter emergency ages below 40 GB
   free, aborts (deleting nothing) if any state file can't be read, and logs every deletion to a CSV.
5. **A weekly archive** ([`ops/archive_old_backups.py`](../ops/archive_old_backups.py)): backup copies of code
   and queue files older than a week are zipped onto a second drive, CRC-verified, and only then removed.

What is **never** deleted automatically: databases, ledgers and queues, configs, and anything a platform
hasn't confirmed yet. If cleanup can't be sure, it keeps the file.

## 3. Notifications

Email over SMTP ([`ops/notifier.py`](../ops/notifier.py)), configured with environment variables only:

```bash
NOTIFY_SMTP_HOST=smtp.gmail.com
NOTIFY_SMTP_PORT=587
NOTIFY_SMTP_USER=<sender address>
NOTIFY_SMTP_PASSWORD=<app password, never your account password>
NOTIFY_TO=<where alerts go>
```

With Gmail, create an **App Password** (Google Account → Security → 2-Step Verification → App passwords) and
store it as a user environment variable through a masked prompt, never in a file in the repo.

| Event | Why you hear about it |
|---|---|
| Reel published (with link) | Confirmation without opening the app |
| TikTok drafts piling up | Inbox uploads stop at TikTok's pending limit until you post some |
| Disk below threshold | Usually means a stuck stage, not just "big files" |
| Clipping stalled | A job hasn't progressed within its expected time |
| Publish outcome uncertain | Never retried automatically: a human checks the account |
| Daily analytics reminder | Habit loop for reviewing what performed |

Alerts are **edge-triggered**: one email when a condition starts (and again only after it has cleared), not
one every run.

The **dashboard** ([remote-access-tailscale.md](remote-access-tailscale.md)) is the pull-based counterpart:
queues, last posts, cadence, storage and every scheduled task's last result, readable from your phone.
