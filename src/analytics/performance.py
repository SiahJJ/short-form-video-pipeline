"""Performance loop: learn which creators, niches, lengths, hooks and hours work - and feed it back.

1. Every published post is stored with its features (creator, niche, trend vs creator clip, length, hook style,
   posting hour, language) and metric snapshots at fixed ages (24 h, 72 h), so posts are compared at the
   same age.
2. Outcome per post = log1p(views at 72 h, else 24 h) minus its platform's median -> a log-lift that is
   comparable across platforms and across big/small accounts.
3. Per factor value, the mean lift is shrunk toward 0 by n / (n + K): a creator with 1 viral post can't look
   better than one with 30 consistently good posts.
4. Outputs drive the pipeline: a +/-5 creator bonus in ranking, the best posting hours for the wake schedule,
   and a human-readable weekly report.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict

K = 8
MAX_BONUS = 5.0
MIN_POSTS = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts(platform TEXT, post_id TEXT, creator TEXT, niche TEXT, trend INTEGER,
    length_s REAL, hook_style TEXT, posted_hour INTEGER, language TEXT, PRIMARY KEY(platform, post_id));
CREATE TABLE IF NOT EXISTS metrics(platform TEXT, post_id TEXT, bucket TEXT, age_h REAL, views INTEGER,
    likes INTEGER, comments INTEGER, PRIMARY KEY(platform, post_id, bucket));
"""


def hook_style(text: str) -> str:
    first = (str(text or "").strip().splitlines() or [""])[0]
    if not first:
        return "none"
    if "?" in first:
        return "question"
    if any(ch.isdigit() for ch in first):
        return "number"
    if not (first[0].isalnum() or first[0].isspace()):
        return "emoji_open"
    letters = [ch for ch in first if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.6:
        return "all_caps"
    return "statement"


def length_bucket(s):
    if s is None:
        return "unknown"
    return "<20s" if s < 20 else "20-35s" if s < 35 else "35-60s" if s < 60 else "60s+"


def due_buckets(age_h: float, have: set[str], buckets=((24, "24h"), (72, "72h"))) -> list[str]:
    return [b for h, b in buckets if age_h >= h and b not in have]


def outcomes(c: sqlite3.Connection):
    rows = c.execute("""
        SELECT p.platform, p.creator, p.niche, p.trend, p.length_s, p.hook_style, p.posted_hour, p.language,
               COALESCE(m72.views, m24.views), COALESCE(m72.likes, m24.likes, 0), COALESCE(m72.comments, m24.comments, 0)
        FROM posts p
        LEFT JOIN metrics m72 ON m72.platform=p.platform AND m72.post_id=p.post_id AND m72.bucket='72h'
        LEFT JOIN metrics m24 ON m24.platform=p.platform AND m24.post_id=p.post_id AND m24.bucket='24h'
        WHERE m72.post_id IS NOT NULL OR m24.post_id IS NOT NULL""").fetchall()
    by = defaultdict(list)
    for r in rows:
        value = r[8] if r[8] is not None else r[9] + 3 * r[10]      # views, else engagement
        by[r[0]].append((r, math.log1p(value or 0)))
    out = []
    for items in by.values():
        med = statistics.median(v for _, v in items)
        for r, v in items:
            out.append(({"creator": r[1] or "?", "niche": r[2] or "other", "trend": "trend" if r[3] else "creator",
                         "length": length_bucket(r[4]), "hook": r[5] or "none",
                         "hour": f"{r[6]:02d}" if r[6] is not None else "?", "language": r[7] or "?"}, v - med))
    return out


def factor_table(rows, k: int = K):
    acc = defaultdict(lambda: defaultdict(list))
    for feats, lift in rows:
        for f, v in feats.items():
            acc[f][v].append(lift)
    return {f: {v: {"n": len(l), "lift": statistics.mean(l), "shrunk": statistics.mean(l) * len(l) / (len(l) + k)}
                for v, l in vals.items()} for f, vals in acc.items()}


def creator_bonus(table, total_posts: int) -> dict[str, float]:
    if total_posts < MIN_POSTS:
        return {}
    return {c: round(max(-1.0, min(1.0, s["shrunk"] / 0.7)) * MAX_BONUS, 2) for c, s in table.get("creator", {}).items()}


def best_hours(table, min_n: int = 5) -> list[int]:
    hours = table.get("hour", {})
    return [int(h) for h in sorted((h for h in hours if h != "?" and hours[h]["n"] >= min_n), key=lambda h: -hours[h]["shrunk"])]


def plan_windows(ranked: list[int], defaults=(8, 11, 14, 17, 20, 23), per_day: int = 6, min_gap: int = 2,
                 earliest: int = 7) -> list[int]:
    """Pick posting windows from the best hours, at least `min_gap` hours apart, topped up with defaults."""
    gap = lambda a, b: min(abs(a - b), 24 - abs(a - b))
    out: list[int] = []
    for h in list(ranked) + list(defaults):
        if (h >= earliest or h == 0) and all(gap(h, x) >= min_gap for x in out):
            out.append(h)
        if len(out) == per_day:
            break
    return sorted(out)
