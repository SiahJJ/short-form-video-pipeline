"""Free, local evidence that a moment makes a good short - used to nudge an LLM's clip scores.

* Most replayed: YouTube's audience-retention heatmap (yt-dlp `--write-info-json` saves it). Moments that
  viewers rewatch are the best clips; a candidate overlapping the peak gets up to +6 points.
* Energy: loudness peaks (laughter, cheering, shouting) relative to the video's own voiced baseline.
* Scene cuts: clip start/end snap to a nearby hard cut so a short never opens or closes mid-shot.

Every signal is optional - missing data means no adjustment, never a failure.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Iterable

import numpy as np

MAX_HEATMAP_BONUS = 6.0
MAX_ENERGY_BONUS = 3.0


def video_id_from_name(media_path: str) -> str | None:
    """yt-dlp names files '<title> [<11-char id>].ext'."""
    m = re.findall(r"\[([A-Za-z0-9_-]{11})\]", Path(media_path).name)
    return m[-1] if m else None


def heatmap(media_path: str, info_dirs: Iterable[Path]) -> list[dict]:
    vid = video_id_from_name(media_path)
    if not vid:
        return []
    for base in info_dirs:
        for info in Path(base).rglob(f"*[[]{vid}[]].info.json"):
            try:
                data = json.loads(info.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            return [h for h in (data.get("heatmap") or []) if "start_time" in h and "value" in h]
    return []


def energy_profile(media_path: str, hop: float = 0.5) -> np.ndarray:
    """Loudness (RMS, dB) per `hop` seconds, from 8 kHz mono audio decoded by ffmpeg."""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", media_path, "-vn", "-ac", "1", "-ar", "8000",
                              "-f", "s16le", "-"], capture_output=True, check=True, timeout=900).stdout
    except (OSError, subprocess.SubprocessError):
        return np.zeros(0)
    return rms_db(np.frombuffer(raw, dtype=np.int16).astype(np.float32), 8000, hop)


def rms_db(samples: np.ndarray, rate: int, hop: float) -> np.ndarray:
    n = int(rate * hop)
    if samples.size < n:
        return np.zeros(0)
    frames = samples[: samples.size // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1.0)


def heat_bonus(c: dict, heat: list[dict]) -> float:
    """Blend of the peak and mean retention inside the clip, relative to the video's average; can be negative."""
    if not heat:
        return 0.0
    vals = [h["value"] for h in heat]
    base, top = float(np.mean(vals)), float(max(vals))
    inside = [h["value"] for h in heat if h["end_time"] > c["start"] and h["start_time"] < c["end"]]
    if not inside or top <= base:
        return 0.0
    rel = (max(inside) * 0.6 + float(np.mean(inside)) * 0.4 - base) / (top - base)
    return round(max(-2.0, min(1.0, rel)) * MAX_HEATMAP_BONUS, 2)


def energy_bonus(c: dict, prof: np.ndarray, hop: float = 0.5) -> float:
    """How far the clip's loudest moments rise above the voiced baseline, in standard deviations."""
    if prof.size < 20:
        return 0.0
    voiced = prof[prof > np.percentile(prof, 20)]
    mu, sd = float(voiced.mean()), float(voiced.std() or 1.0)
    seg = prof[int(c["start"] / hop): int(c["end"] / hop) + 1]
    if seg.size == 0:
        return 0.0
    peak = (float(np.percentile(seg, 95)) - mu) / sd
    return round(max(0.0, min(1.0, (peak - 1.0) / 1.5)) * MAX_ENERGY_BONUS, 2)


def scene_cuts(media_path: str, at: float, window: float = 1.5) -> list[float]:
    start = max(0.0, at - window)
    try:
        err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{start:.2f}", "-t", f"{2 * window:.2f}",
                              "-i", media_path, "-an", "-vf", "scale=320:-2,select='gt(scene,0.32)',showinfo",
                              "-f", "null", "-"], capture_output=True, text=True, timeout=60).stderr
    except (OSError, subprocess.SubprocessError):
        return []
    return [start + float(t) for t in re.findall(r"pts_time:([0-9.]+)", err)]


def snap(c: dict, s_cuts: list[float], e_cuts: list[float], duration: float) -> dict:
    """Start moves to the last cut just before it, end to the first cut just after it (within the window)."""
    s = [t for t in s_cuts if t <= c["start"] + 0.4]
    e = [t for t in e_cuts if t >= c["end"] - 0.4]
    if s:
        c["start"] = round(max(0.0, max(s)), 2)
    if e:
        c["end"] = round(min(duration, min(e)), 2)
    c["length"] = round(c["end"] - c["start"], 2)
    return c


def apply(candidates: list[dict], heat: list[dict], prof: np.ndarray) -> list[dict]:
    """Add evidence bonuses to each candidate's 0-100 score and record why."""
    for c in candidates:
        hb, eb = heat_bonus(c, heat), energy_bonus(c, prof)
        c["llm_score"] = c.get("llm_score", c["score"])
        c["signals"] = {"most_replayed": hb, "energy": eb}
        c["score"] = int(max(0, min(100, round(c["llm_score"] + hb + eb))))
    return candidates
