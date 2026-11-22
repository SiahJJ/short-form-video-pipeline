"""Archive old backup files out of the pipeline folder, ideally onto a second drive.

    python archive_old_backups.py --root <pipeline folder> --dest <archive folder> [--days 7] [--apply]

Backup-style files and folders (`*.bak`, `*before_*`, `*backup*`, `manifest_before_*`, ...) older than
--days are zipped into <dest>/code_backups_<date>.zip. The zip is re-read and every entry is checked
(CRC) before the originals are deleted. Recent backups stay in place. Never touches venvs, node_modules,
databases, live config, ledgers or manifests (only their *backup* copies).
Dry run by default; --apply archives and removes.
"""
import argparse, os, re, sys, time, zipfile
from pathlib import Path

ROOT = Path(".")          # set by --root
DEST = Path("archive")    # set by --dest
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git"}
FILE_RE = re.compile(r"(\.bak$|\.backup|backup_\d|before[_-]|\.before|^manifest_before_|^ledger_before_|"
                     r"\.pre[_-]|\.fix\d+_|\.incomplete_|\.after-failed|_backup\.)", re.I)
DIR_RE = re.compile(r"(backup|recovery_report|repair_backup|_backups$)", re.I)


def collect(days):
    cutoff = time.time() - days * 86400
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        here = Path(dirpath)
        for d in list(dirnames):
            full = here / d
            if DIR_RE.search(d) and full.stat().st_mtime < cutoff:
                for f in full.rglob("*"):
                    if f.is_file(): out.append(f)
                dirnames.remove(d)
        for f in filenames:
            p = here / f
            if FILE_RE.search(f) and p.stat().st_mtime < cutoff:
                out.append(p)
    return out


def main():
    global ROOT, DEST
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--root", required=True); ap.add_argument("--dest", required=True)
    a = ap.parse_args()
    ROOT, DEST = Path(a.root).resolve(), Path(a.dest)
    files = collect(a.days)
    total = sum(f.stat().st_size for f in files)
    print(f"{len(files)} backup files older than {a.days:g} days, {total/1e9:.2f} GB")
    if not a.apply or not files:
        for f in files[:15]: print("  ", f)
        return
    DEST.mkdir(parents=True, exist_ok=True)
    z = DEST / f"code_backups_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            zf.write(f, f.relative_to(ROOT.parent).as_posix())
    with zipfile.ZipFile(z) as zf:                       # verify before deleting anything
        bad = zf.testzip()
        names = set(zf.namelist())
    if bad or len(names) < len(set(f.relative_to(ROOT.parent).as_posix() for f in files)):
        sys.exit(f"Archive check failed ({bad}); nothing deleted. Archive kept at {z}")
    removed = 0
    for f in files:
        try: f.unlink(); removed += 1
        except OSError as ex: print("kept (in use):", f, ex)
    for dirpath, dirnames, filenames in os.walk(ROOT, topdown=False):   # drop backup folders left empty
        p = Path(dirpath)
        if DIR_RE.search(p.name) and not any(p.iterdir()):
            p.rmdir()
    print(f"archived to {z} ({z.stat().st_size/1e9:.2f} GB), removed {removed} originals")


if __name__ == "__main__":
    main()
