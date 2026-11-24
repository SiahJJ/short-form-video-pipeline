"""PC -> Pi sync for the automation mirror (PI_MIRROR_V1, 2026-11-23).

Runs every 5 minutes while the PC is awake (scheduled task "Automation Pi Mirror Sync") and at the end of each
work window, right before the PC sleeps:
  1. pulls 'Posted' taps made on the Pi's helper and applies them to the PC's TikTok checklist;
  2. snapshots the dashboard (/api/status) and helper (/api/tiktok) from the local dashboard;
  3. makes small 480p previews of the drafts waiting in the TikTok inbox (and the next few to send);
  4. uploads pages + data + new previews to the Pi over SSH (Tailscale), removes previews no longer needed.
Uses a dedicated SSH key (no password prompts). Safe to run while the Pi is unreachable - it just retries next time.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PI = "pi@your-pi-tailscale-ip"              # the Pi's Tailscale address
REMOTE = "automation-mirror"                  # ~/automation-mirror on the Pi
KEY = Path.home() / ".ssh" / "id_ed25519_pi"
HERE = Path(__file__).resolve().parent
DASH = "http://127.0.0.1:8790"
WEB_SRC = Path(r"C:\AI\dashboard")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"     # ffmpeg on PATH
CACHE = HERE / "preview_cache"                # 480p previews, reused between runs
LOG = HERE / "sync.log"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SSH_OPTS = ["-i", str(KEY), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def ssh(cmd, timeout=60):
    return subprocess.run(["ssh", *SSH_OPTS, PI, cmd], capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW)


def get(path):
    with urllib.request.urlopen(DASH + path, timeout=30) as r:
        return json.load(r)


def pull_marks():
    r = ssh(f"cd ~/{REMOTE}/data 2>/dev/null && [ -f marks.jsonl ] && mv marks.jsonl marks.syncing && "
            f"cat marks.syncing && rm -f marks.syncing || true")
    if r.returncode != 0:
        raise ConnectionError((r.stderr or r.stdout).strip()[:200])
    marks = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
    if marks:
        sys.path.insert(0, str(WEB_SRC))
        import server as dash                       # the dashboard's own checklist writer
        for m in marks:
            n = dash.tt_mark({str(q) for q in m.get("queues", [])}, bool(m.get("undo")))
            log(f"applied Pi mark {m.get('queues')} undo={bool(m.get('undo'))} ({n} rows)")
    return len(marks)


def next_wake():
    try:
        cfg = json.loads(Path(r"C:\AI\analytics\config\work_windows.json").read_text(encoding="utf-8"))
        now = datetime.now()
        slots = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in cfg.get("post_hours", [])]
        nh, nm = (int(x) for x in str(cfg.get("night_time", "02:30")).split(":"))
        slots.append(now.replace(hour=nh, minute=nm, second=0, microsecond=0))
        ch, cm = (int(x) for x in str(cfg.get("catchup_time", "22:30")).split(":"))
        slots.append(now.replace(hour=ch, minute=cm, second=0, microsecond=0))
        slots = sorted(t if t > now else t + timedelta(days=1) for t in slots)
        return slots[0].strftime("%a %I:%M %p").replace(" 0", " ")
    except Exception:
        return "next window"


def preview(qid, src: Path) -> Path | None:
    CACHE.mkdir(exist_ok=True)
    out = CACHE / f"{qid}.mp4"
    if out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    r = subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vf", "scale=-2:854", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
                        str(out)], capture_output=True, timeout=300, creationflags=NO_WINDOW)
    return out if r.returncode == 0 and out.is_file() else None


def main():
    try:
        marks = pull_marks()
    except Exception as ex:
        return log(f"Pi unreachable, will retry next run: {ex}")
    status, tiktok = get("/api/status"), get("/api/tiktok")
    sys.path.insert(0, str(WEB_SRC))
    import server as dash
    items = [i for d in tiktok.get("days", []) for i in d.get("items", [])]
    want = [i["queue"] for i in items if i.get("in_inbox")]
    want += [i["queue"] for i in sorted(items, key=lambda i: -int(i["queue"])) if not i.get("uploaded")][:6]
    stage = Path(tempfile.mkdtemp(prefix="pimirror_"))
    try:
        (stage / "videos").mkdir()
        keep = []
        for q in dict.fromkeys(want):
            src = dash.tt_video_path(q)
            if src and (pv := preview(q, src)):
                keep.append(q)
                shutil.copy2(pv, stage / "videos" / f"{q}.mp4")
        (stage / "status.json").write_text(json.dumps(status), encoding="utf-8")
        (stage / "tiktok.json").write_text(json.dumps(tiktok), encoding="utf-8")
        (stage / "meta.json").write_text(json.dumps({"pushed_at": datetime.now(timezone.utc).astimezone().isoformat(),
                                                     "next_wake": next_wake()}), encoding="utf-8")
        for f in ("index.html", "tiktok.html"):
            shutil.copy2(WEB_SRC / f, stage / f)
        shutil.copy2(HERE / "mirror_server.py", stage / "mirror_server.py")
        shutil.copy2(HERE / "pi_guard.sh", stage / "pi_guard.sh")
        # only send previews the Pi doesn't already have - and none at all if its disk is low (DISK_GUARD)
        have = set(ssh(f"ls ~/{REMOTE}/data/videos 2>/dev/null").stdout.split())
        try:
            free_mb = int(ssh("df --output=avail -k ~ | tail -1").stdout.strip()) // 1024
        except ValueError:
            free_mb = 0
        for v in list((stage / "videos").iterdir()):
            if v.name in have or free_mb < 1024:
                v.unlink()
        if free_mb < 1024:
            log(f"Pi has only {free_mb} MB free - skipping previews this run")
        ssh(f"mkdir -p ~/{REMOTE}/incoming ~/{REMOTE}/data/videos ~/{REMOTE}/web")
        r = subprocess.run(["scp", "-q", "-r", *SSH_OPTS, *[str(p) for p in stage.iterdir()], f"{PI}:~/{REMOTE}/incoming/"],
                           capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)
        if r.returncode != 0:
            return log(f"upload failed: {(r.stderr or '').strip()[:200]}")
        keep_list = " ".join(f"{q}.mp4" for q in keep) or "none"
        r = ssh(f"cd ~/{REMOTE} && cp -f incoming/*.json data/ && cp -f incoming/*.html web/ && "
                f"cp -f incoming/mirror_server.py incoming/pi_guard.sh . && (mv -f incoming/videos/*.mp4 data/videos/ 2>/dev/null || true) && "
                f"rm -rf incoming/* && cd data/videos && for f in *.mp4; do case ' {keep_list} ' in *\" $f \"*) ;; *) rm -f \"$f\";; esac; done")
        if r.returncode != 0:
            return log(f"publish on Pi failed: {(r.stderr or '').strip()[:200]}")
        log(f"pushed snapshot ({len(items)} helper items, {len(keep)} previews, {marks} marks pulled)")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    for old in CACHE.glob("*.mp4"):                  # previews no longer needed
        if old.stem not in keep:
            old.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        log(f"sync failed: {type(ex).__name__}: {ex}")
