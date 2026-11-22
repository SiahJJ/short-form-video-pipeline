import random
import sqlite3

from analytics.performance import (SCHEMA, best_hours, creator_bonus, due_buckets, factor_table, hook_style,
                                   outcomes, plan_windows)


def synthetic_db():
    """Made-up channel data: 'GoodChannel' gets ~3x views, hour 20 gets ~2x, 60s+ clips get half."""
    rnd = random.Random(7)
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    for i in range(240):
        creator = rnd.choice(["GoodChannel", "AvgChannel", "WeakChannel"])
        hour = rnd.choice([9, 14, 20, 22])
        length = rnd.choice([15, 30, 45, 75])
        views = 1000 * {"GoodChannel": 3, "AvgChannel": 1, "WeakChannel": 0.4}[creator] \
            * (2 if hour == 20 else 1) * (0.5 if length >= 60 else 1) * rnd.uniform(0.7, 1.3)
        c.execute("INSERT INTO posts VALUES(?,?,?,?,?,?,?,?,?)", ("youtube", f"p{i}", creator, "gaming", 0, length, "statement", hour, "en"))
        c.execute("INSERT INTO metrics VALUES(?,?,?,?,?,?,?)", ("youtube", f"p{i}", "72h", 80, int(views), 0, 0))
    return c


def test_learns_creators_hours_and_lengths():
    rows = outcomes(synthetic_db())
    t = factor_table(rows)
    assert t["creator"]["GoodChannel"]["shrunk"] > t["creator"]["AvgChannel"]["shrunk"] > t["creator"]["WeakChannel"]["shrunk"]
    assert best_hours(t)[0] == 20
    assert t["length"]["60s+"]["shrunk"] < t["length"]["20-35s"]["shrunk"]
    b = creator_bonus(t, len(rows))
    assert b["GoodChannel"] > 0 > b["WeakChannel"] and abs(b["GoodChannel"]) <= 5


def test_no_bonus_without_enough_data():
    assert creator_bonus({"creator": {"X": {"shrunk": 2.0, "n": 3}}}, total_posts=5) == {}


def test_snapshots_only_at_fixed_ages():
    assert due_buckets(10, set()) == []
    assert due_buckets(30, set()) == ["24h"]
    assert due_buckets(80, {"24h"}) == ["72h"]


def test_window_plan_is_spaced_and_topped_up():
    assert plan_windows([9, 20, 0, 12, 4, 15, 21, 14]) == [0, 9, 12, 15, 17, 20]   # 4 AM too early; 21/14 too close
    assert plan_windows([]) == [8, 11, 14, 17, 20, 23]


def test_hook_styles():
    assert hook_style("Can he really do it?") == "question"
    assert hook_style("3 tricks nobody knows") == "number"
    assert hook_style("🔥 Huge play") == "emoji_open"
    assert hook_style("HUGE PLAY") == "all_caps"
