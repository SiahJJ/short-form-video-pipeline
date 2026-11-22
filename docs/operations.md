# Running it unattended on a home PC: wake schedules, storage and notifications

The pipeline is a set of small scripts run by **Windows Task Scheduler**. There is no always-on server: the PC
can sleep, wakes itself for each job, stays awake only while work is happening, and tells you by email when
something needs you.

## 1. Waking up and running on schedule

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
