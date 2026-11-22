"""Storage guardian: keep a single-disk media pipeline from filling the drive.

Removes only files the pipeline provably no longer needs, in rule order, and logs every deletion to CSV.
It never decides on unknown state: if any state source can't be read, the run aborts and deletes nothing.

Rules (ages shrink in emergency mode, when free space < `emergency_gb`):
  R1 render scratch          older than 3 h (2 h)
  R2 clipper's source copy   30 min after its job is done; failed jobs after 12 h
  R3 source download         2 h (1 h) after clipping finished
  R4 finished clip           every platform that queued it has confirmed it, + buffer (72 h / 24 h)
  R5 exact duplicate         same name + size already saved elsewhere, after 6 h
  R7 abandoned partial       .part / .ytdl untouched for 3 h (an active download rewrites it constantly)

Plus a NEVER list (databases, queues, configs) checked last as a hard safety net.
"""
from __future__ import annotations

import csv
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

Candidate = tuple[str, Path]


def age_h(p: Path) -> float:
    return (time.time() - p.stat().st_mtime) / 3600


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 2**30


@dataclass
class State:
    """What the rest of the pipeline still needs. Built by the caller from its own databases/ledgers."""
    job_done_sources: set[str] = field(default_factory=set)     # resolved lower-case paths
    job_failed_sources: dict[str, float] = field(default_factory=dict)  # path -> hours since failure
    job_active_sources: set[str] = field(default_factory=set)
    finished_video_ids: set[str] = field(default_factory=set)   # clipping finished for these sources
    clip_confirmations: dict[str, list[bool]] = field(default_factory=dict)  # clip path -> per-platform ok


@dataclass
class Dirs:
    work: Path
    uploads: Path
    downloads: Path
    clips: list[Path]
    never: list[Path]


def key(p: Path) -> str:
    return str(p.resolve()).lower()


def candidates(d: Dirs, st: State, emergency: bool, video_id: Callable[[str], str | None]) -> list[Candidate]:
    out: list[Candidate] = []
    files = lambda root: (p for p in root.rglob("*") if p.is_file()) if root.is_dir() else iter(())
    for p in files(d.work):                                                     # R1
        if age_h(p) > (2 if emergency else 3):
            out.append(("R1 render scratch", p))
    for p in files(d.uploads):                                                  # R2
        k = key(p)
        if k in st.job_active_sources or age_h(p) < 0.5:
            continue
        if k in st.job_done_sources or st.job_failed_sources.get(k, 0) > 12:
            out.append(("R2 clipper source copy", p))
    for p in files(d.downloads):
        if p.suffix.lower() in (".part", ".ytdl") or ".part-Frag" in p.name:     # R7
            if age_h(p) >= 3:
                out.append(("R7 abandoned partial download", p))
        elif video_id(p.name) in st.finished_video_ids and age_h(p) >= (1 if emergency else 2):
            out.append(("R3 source download", p))                               # R3
    saved: dict[tuple[str, int], Path] = {}
    for root in d.clips:                                                        # R4 / R5
        for p in files(root):
            oks = st.clip_confirmations.get(key(p))
            if oks and all(oks) and age_h(p) >= (24 if emergency else 72):
                out.append(("R4 confirmed on every platform", p))
            elif not oks:
                sig = (p.name, p.stat().st_size)
                if sig in saved and age_h(p) >= 6:
                    out.append(("R5 exact duplicate", p))
                saved.setdefault(sig, p)
    never = [n.resolve() for n in d.never]
    return [(r, p.resolve()) for r, p in out if not any(p.resolve().is_relative_to(n) for n in never)]


def run(d: Dirs, build_state: Callable[[], State], video_id, log_csv: Path,
        emergency_gb: float = 40, apply: bool = False) -> dict:
    st = build_state()                              # raises on unreadable state -> nothing is deleted
    emergency = free_gb(d.downloads) < emergency_gb
    cands = candidates(d, st, emergency, video_id)
    removed, freed = [], 0
    if apply:
        log_csv.parent.mkdir(parents=True, exist_ok=True)
        new = not log_csv.exists()
        with log_csv.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["utc", "rule", "path", "bytes"])
            for rule, p in cands:
                try:
                    stt = p.stat()
                    p.unlink()
                except OSError:
                    continue                        # in use / already gone: try again next run
                freed += stt.st_size if stt.st_nlink == 1 else 0   # hard-linked bytes free with the last link
                removed.append(p)
                w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), rule, str(p), stt.st_size])
    return {"emergency": emergency, "candidates": len(cands), "removed": len(removed), "freed_gb": freed / 1e9}
