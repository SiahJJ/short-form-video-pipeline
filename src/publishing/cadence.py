"""Posting cadence under a rolling 24-hour platform cap.

* Normal: spread the daily allowance evenly (24 h / cap), or a fixed minimum gap - whichever is larger.
* Backlog: a random 5-10 min gap (seeded by the last post so it doesn't re-roll every check).
* End-of-day burst: in the last hour of the day, if fewer than `cap` posts went out in the past 24 h, the
  remaining queue goes back to back with the 5-10 min gap so unused allowance isn't wasted.
* The rolling cap always wins: never more than `cap` posts in any 24-hour window.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Cadence:
    cap_24h: int = 50
    min_gap_min: int = 30
    backlog_threshold: int = 5
    burst_gap: tuple[int, int] = (5, 10)
    burst_hour: int = 23
    even_pace: bool = True

    def gap_minutes(self, last: datetime, backlog: int, burst: bool) -> int:
        if burst or backlog >= self.backlog_threshold:
            gap = random.Random(int(last.timestamp())).randint(*self.burst_gap)
        else:
            gap = self.min_gap_min
        if self.even_pace and not burst:
            gap = max(gap, -(-1440 // self.cap_24h))  # ceil(24h / cap)
        return gap

    def wait_seconds(self, posts: list[datetime], now: datetime, local_hour: int, backlog: int) -> float:
        """Seconds until the next post is allowed (0 = now)."""
        if not posts:
            return 0.0
        posts = sorted(posts)
        recent = [t for t in posts if t > now - timedelta(hours=24)]
        burst = local_hour == self.burst_hour and len(recent) < self.cap_24h
        wait = (posts[-1] + timedelta(minutes=self.gap_minutes(posts[-1], backlog, burst)) - now).total_seconds()
        if len(recent) >= self.cap_24h:               # rolling cap: wait for the oldest post to age out
            wait = max(wait, (recent[-self.cap_24h] + timedelta(hours=24) - now).total_seconds())
        return max(0.0, wait)
