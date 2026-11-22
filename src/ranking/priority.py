"""Which clip goes out next, per platform.

Every clip carries a 0-100 quality score from the clipper (an LLM's rating of the moment, nudged by free evidence -
see clip_signals). Platforms have different budgets, so each ranks the same scores its own way:

* YouTube   - ~10 uploads/day of quota: strictly highest score first; source-video views break ties; then
              each upload gets a scheduled `publishAt` in the next free peak-hour slot.
* Instagram - 50 posts/day: priority = score + timeliness + creator performance - staleness. Only the top
              ACTIVE drafts may publish; the rest wait and rejoin when they rank in (a short active queue keeps
              old clips from clogging it).
* TikTok    - drafts sent to the creator's inbox best-first, a few at a time (pending-draft limit).
* Facebook  - follows Instagram's order (roll-over of confirmed Reels), so it inherits this ranking.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_SCORE = 75.0      # unknown score: assume "decent", never block a clip for missing metadata
TREND_BONUS = 5.0         # trending topics are worth more while they're hot
MAX_CREATOR_BONUS = 5.0
STALE_AFTER_DAYS, MAX_STALE_PENALTY = 3, 10.0
ACTIVE = 25


@dataclass
class Clip:
    id: str
    score: float | None
    creator: str
    trend: bool = False
    source_published: datetime | None = None
    source_views: int = 0
    blocked: bool = False         # language / content gate: never publishes


def creator_bonus(engagement: dict[str, list[float]], min_posts_total: int = 20, prior: int = 8) -> dict[str, float]:
    """Creators whose posts out-perform the average get up to +5, under-performers down to -5.

    `engagement` maps creator -> per-post engagement (e.g. views or likes + 3*comments, at a fixed post age).
    The z-score is halved and clipped, then shrunk toward 0 by n/(n+prior): one lucky post can't swing ranking.
    """
    allv = [x for v in engagement.values() for x in v]
    if len(allv) < min_posts_total:
        return {}
    mu, sd = statistics.mean(allv), statistics.pstdev(allv) or 1.0
    out = {}
    for c, vals in engagement.items():
        z = (statistics.mean(vals) - mu) / sd
        out[c] = round(max(-1.0, min(1.0, z / 2)) * MAX_CREATOR_BONUS * len(vals) / (len(vals) + prior), 2)
    return out


def instagram_priority(c: Clip, bonus: dict[str, float], now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    base = c.score if c.score is not None else DEFAULT_SCORE
    age_days = (now - c.source_published).days if c.source_published else 0
    stale = min(MAX_STALE_PENALTY, max(0.0, age_days - STALE_AFTER_DAYS))
    return round(base + (TREND_BONUS if c.trend else 0.0) + bonus.get(c.creator, 0.0) - stale, 2)


def rank_instagram(clips: list[Clip], bonus: dict[str, float], now=None, active: int = ACTIVE):
    """Returns [(clip, priority, rank, may_publish)] best first."""
    scored = sorted(((c, instagram_priority(c, bonus, now)) for c in clips), key=lambda x: (-x[1], x[0].id))
    return [(c, p, i, i <= active and not c.blocked) for i, (c, p) in enumerate(scored, 1)]


def rank_youtube(clips: list[Clip]) -> list[Clip]:
    """Unknown scores last; then score; then how big the source video was."""
    return sorted((c for c in clips if not c.blocked),
                  key=lambda c: (c.score is None, -(c.score or 0), -c.source_views, c.id))


def next_peak_slot(after: datetime, taken: set[datetime], peak_hours=(9, 12, 15, 18, 21), tz=timezone.utc) -> datetime:
    """First free peak-hour slot after `after` (YouTube publishAt): uploads happen any time, go live at peaks."""
    day = after.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    for d in range(0, 14):
        for h in peak_hours:
            slot = day.replace(hour=h) + timedelta(days=d)
            if slot > after and slot not in taken:
                return slot
    raise RuntimeError("no free slot in two weeks")
