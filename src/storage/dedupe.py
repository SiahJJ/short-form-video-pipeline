"""Store duplicate source videos once, using NTFS/POSIX hard links.

The clipper keeps its own full copy of every source it is given (`uploads/<job>-<name>`), while the original
stays in `downloads/`. Both paths are needed for a while, so instead of deleting either, the download is
atomically replaced by a hard link to the clipper's copy: both paths keep working, the bytes are stored
once, and the space frees automatically when the last link is removed.

Only exact duplicates (same name after the job prefix, same byte size) on the same volume are linked.
"""
from __future__ import annotations

import os
from pathlib import Path

VIDEO = {".mp4", ".mkv", ".webm", ".mov"}


def same_file(a: Path, b: Path) -> bool:
    sa, sb = os.stat(a), os.stat(b)
    return sa.st_ino == sb.st_ino and sa.st_dev == sb.st_dev


def link_over(target: Path, keep: Path) -> None:
    """Replace `target` with a hard link to `keep`. Atomic: on any failure the original stays."""
    tmp = target.with_name(target.name + ".dedupe-tmp")
    if tmp.exists():
        tmp.unlink()
    os.link(keep, tmp)
    os.replace(tmp, target)


def dedupe(uploads: Path, roots: list[Path], apply: bool = False) -> int:
    """Returns bytes reclaimed (or reclaimable in a dry run)."""
    by_name: dict[str, list[Path]] = {}
    for r in roots:
        for p in (r.rglob("*") if r.is_dir() else []):
            if p.is_file() and p.suffix.lower() in VIDEO:
                by_name.setdefault(p.name, []).append(p)
    saved = 0
    for up in sorted(uploads.iterdir()) if uploads.is_dir() else []:
        if not up.is_file() or "-" not in up.name:
            continue
        for src in by_name.get(up.name.split("-", 1)[1], []):
            try:
                if src.stat().st_size != up.stat().st_size or same_file(src, up):
                    continue
                if apply:
                    link_over(src, up)
                saved += up.stat().st_size
            except OSError:
                continue
    return saved
