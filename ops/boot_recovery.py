"""Put an unattended pipeline back together after a crash, power cut or surprise restart.

Run it at sign-in (a Task Scheduler "At log on" trigger) and at the start of every work window. It is safe to
run any time: it only restarts what is down and removes state that can no longer be true. It never retries an
upload whose outcome is unknown - it reports it, because a retry could double-post.

  python boot_recovery.py          recover
  python boot_recovery.py --check  report only, change nothing

Edit the CONFIG block for your own ports, task names and paths.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ----------------------------------------------------------------- CONFIG
DATA = Path(__file__).resolve().parent / "data"
FLAG = DATA / "work_window.json"            # {"until": iso} while a work window runs
LOG = DATA / "work_window.log"
JOB_RECORDS = Path("job_records")           # one JSON per render job: {"status": "running" | "done" | "error"}
JOB_API = "http://127.0.0.1:8765/api/status/{}"
UPLOAD_LEDGERS = [DATA / "fb_ledger.json"]  # {item_id: {"status": ..., "started_at": iso}}
IN_FLIGHT = ("uploading", "publishing")
SERVICES = {                                # port -> (label, scheduled task that starts it)
    8765: ("Render API", "Pipeline Render Server"),
    8790: ("Dashboard", "Pipeline Dashboard"),
    8766: ("Video server", "Pipeline Video Server"),
}
LLM_PORT, LLM_CMD = 11434, ["ollama", "serve"]
NIGHT_TASK, NIGHT_MARKER, NIGHT_EVERY_H = "Pipeline Work Window - Night", "NIGHT WINDOW start", 26
# -------------------------------------------------------------------------

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)
CHECK_ONLY = False


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} RECOVERY {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def listening(port, timeout=2.0):
    for host in ("127.0.0.1", "::1"):       # some servers bind IPv6 localhost only
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            pass
    return False


def run_task(name):
    if CHECK_ONLY:
        return "check-only"
    r = subprocess.run(["schtasks", "/Run", "/TN", name], capture_output=True, text=True, creationflags=NO_WINDOW)
    return "started" if r.returncode == 0 else (r.stderr or r.stdout).strip()[:100]


def window_running(kind=""):
    """True if a work_window.py process (optionally of `kind`) is alive."""
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object CommandLine"],
                       capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
    return any(f"work_window.py {kind}".strip() in l for l in r.stdout.splitlines())


def clear_stale_flag():
    """A work-window flag outlives a crash; publishers would keep using short burst gaps until it expires."""
    if not FLAG.exists():
        return False
    try:
        until = datetime.fromisoformat(json.loads(FLAG.read_text(encoding="utf-8"))["until"])
    except (OSError, ValueError, KeyError):
        until = datetime.min.replace(tzinfo=timezone.utc)
    if until > datetime.now(timezone.utc) and window_running():
        return False
    log("stale work-window flag -> removed")
    if not CHECK_ONLY:
        FLAG.unlink(missing_ok=True)
    return True


def mark_orphaned_jobs():
    """The render server keeps live jobs in memory; a record still 'running' that it doesn't know is dead."""
    if not listening(int(JOB_API.split(":")[2].split("/")[0])):
        return []
    marked = []
    for f in JOB_RECORDS.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("status") != "running":
            continue
        try:
            urllib.request.urlopen(JOB_API.format(f.stem), timeout=5).close()
            continue
        except urllib.error.HTTPError as e:
            if e.code != 404:
                continue
        except Exception:
            continue
        log(f"job {f.stem} was interrupted -> marked error (the worker re-submits it)")
        marked.append(f.stem)
        if not CHECK_ONLY:
            rec.update(status="error", error="interrupted by restart")
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
            tmp.replace(f)                    # atomic: a second crash can't leave half a file
    return marked


def report_interrupted_uploads(older_than=timedelta(hours=1)):
    found = []
    cutoff = datetime.now(timezone.utc) - older_than
    for path in UPLOAD_LEDGERS:
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item, e in ledger.items():
            try:
                started = datetime.fromisoformat(str(e.get("started_at")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if e.get("status") in IN_FLIGHT and started < cutoff:
                found.append(item)
                log(f"{path.stem} {item} stopped while '{e['status']}' - NOT retried; check the platform by hand")
    return found


def ensure_services():
    down = []
    for port, (label, task) in SERVICES.items():
        if not listening(port):
            down.append(label)
            log(f"{label} not listening on :{port} -> {run_task(task)}")
    if LLM_PORT and not listening(LLM_PORT):
        down.append("LLM")
        if not CHECK_ONLY:
            try:
                subprocess.Popen(LLM_CMD, creationflags=DETACHED, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log("local LLM not running -> started")
            except OSError as ex:
                log(f"local LLM not running and can't start: {ex}")
    return down


def missed_night_window(now=None):
    """Start of the last night window, if it is older than NIGHT_EVERY_H (or never ran)."""
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    last = next((datetime.fromisoformat(l.split(" ", 1)[0]) for l in reversed(lines) if NIGHT_MARKER in l), None)
    if last and (now or datetime.now()) - last < timedelta(hours=NIGHT_EVERY_H):
        return False
    return True


def main():
    global CHECK_ONLY
    CHECK_ONLY = "--check" in sys.argv
    log("start" + (" (check only)" if CHECK_ONLY else ""))
    if not CHECK_ONLY:
        time.sleep(60)                        # let boot-time servers come up first
    clear_stale_flag()
    down = ensure_services()
    mark_orphaned_jobs()
    report_interrupted_uploads()
    if missed_night_window() and not window_running("night"):
        log(f"night window missed -> {run_task(NIGHT_TASK)}")
    log("done - " + ("all services up" if not down else "was down: " + ", ".join(down)))


if __name__ == "__main__":
    main()
