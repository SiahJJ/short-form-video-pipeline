"""Keep Windows awake for exactly as long as a command runs, then let it sleep normally.

    python run_awake.py -- python long_job.py --apply

Uses SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED): the system won't idle-sleep while the flag is
held; it is cleared when the job ends (or this process dies). The display may still turn off.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def set_state(flags: int) -> None:
    fn = ctypes.WinDLL("kernel32", use_last_error=True).SetThreadExecutionState
    fn.argtypes, fn.restype = [ctypes.c_uint], ctypes.c_uint
    if fn(flags) == 0:
        raise ctypes.WinError(ctypes.get_last_error())


def main() -> int:
    cmd = sys.argv[1:]
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    if not cmd:
        sys.exit("usage: run_awake.py -- <command> [args...]")
    set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        return subprocess.call(cmd)
    finally:
        set_state(ES_CONTINUOUS)          # release: normal sleep rules apply again


if __name__ == "__main__":
    sys.exit(main())
