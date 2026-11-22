"""BOOT_NOTICE_V1 (2026-11-22): email as soon as the PC is back after a restart or power cut.

Runs at boot (before anyone signs in). Waits for internet, gives automatic sign-in a few minutes, then sends
one immediate email: when it came back, why it went down (power loss / crash / Windows Update restart), and
whether it signed in by itself - if not, sign in from your phone (Chrome Remote Desktop) to resume posting.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOG = Path(r"C:\AI\analytics\data\work_window.log")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} BOOT NOTICE {msg}\n")


def online():
    try:
        socket.create_connection(("smtp.gmail.com", 587), timeout=5).close()
        return True
    except OSError:
        return False


def ps(cmd):
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
                          capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW).stdout.strip()


def why_down():
    """Most recent shutdown reason from the System log, before this boot."""
    out = ps(r"""
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$e = Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,6008,1074,6006} -MaxEvents 20 -ErrorAction SilentlyContinue |
     Where-Object { $_.TimeCreated -le $boot.AddMinutes(5) } | Select-Object -First 1
if (-not $e) { 'unknown' }
elseif ($e.Id -in 41,6008) { 'unexpected shutdown (power loss or crash) - last seen running ' + $e.TimeCreated.ToString('ddd MMM d h:mm tt') }
elseif ($e.Id -eq 1074) { 'planned restart: ' + (($e.Message -split "`n")[0]).Trim() }
else { 'normal shutdown' }""")
    return out or "unknown"


def signed_in():
    out = ps("(Get-CimInstance Win32_Process -Filter \"Name='explorer.exe'\" | Measure-Object).Count")
    return out.strip() not in ("", "0")


def main(test=False):
    boot = ps("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('ddd MMM d h:mm tt')")
    for _ in range(60):                       # up to 10 min for the network
        if online():
            break
        time.sleep(10)
    if not test:
        time.sleep(240)                       # give automatic sign-in time to finish
    reason, ok = why_down(), signed_in()
    subject = ("TEST - " if test else "") + ("PC back online - automation resumed" if ok
               else "ACTION NEEDED: PC back online but NOT signed in - posting paused")
    body = (f"The automation PC started at {boot}.\n"
            f"Why it went down: {reason}\n"
            f"Signed in automatically: {'yes - the screen locks itself; posting continues' if ok else 'NO'}\n\n"
            + ("" if ok else
               "Posting windows, Facebook and TikTok only run while signed in.\n"
               "Sign in from your phone: Chrome Remote Desktop app > this PC > enter your PIN > sign in to Windows.\n"
               "Uploads resume within minutes; nothing is lost while it waits.\n"))
    sys.path.insert(0, r"C:\AI\yt-automation")
    from automation.notifier import send_email
    send_email(subject, body, force=True)
    log(f"sent: {subject} ({reason})")


if __name__ == "__main__":
    try:
        main(test="--test" in sys.argv)
    except Exception as ex:
        log(f"failed: {type(ex).__name__}: {ex}")
