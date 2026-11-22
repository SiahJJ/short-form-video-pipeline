from datetime import datetime, timedelta, timezone

from ranking.priority import Clip, creator_bonus, next_peak_slot, rank_instagram, rank_youtube

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def test_youtube_is_strictly_best_score_first_with_view_tiebreak():
    clips = [Clip("a", 80, "x", source_views=10), Clip("b", 92, "y"), Clip("c", None, "z"),
             Clip("d", 80, "w", source_views=99), Clip("e", 99, "v", blocked=True)]
    assert [c.id for c in rank_youtube(clips)] == ["b", "d", "a", "c"]


def test_instagram_trend_bonus_and_staleness():
    fresh_trend = Clip("t", 80, "news", trend=True, source_published=NOW - timedelta(days=1))
    old = Clip("o", 88, "pod", source_published=NOW - timedelta(days=20))     # 88 - 10 (capped penalty)
    plain = Clip("p", 82, "game", source_published=NOW - timedelta(days=2))
    ranked = rank_instagram([old, plain, fresh_trend], {}, NOW)
    assert [(c.id, p) for c, p, _, _ in ranked] == [("t", 85.0), ("p", 82.0), ("o", 78.0)]


def test_only_top_active_may_publish_and_blocked_never():
    clips = [Clip(str(i), 90 - i, "c") for i in range(5)] + [Clip("blk", 99, "c", blocked=True)]
    ranked = rank_instagram(clips, {}, NOW, active=3)
    allowed = [c.id for c, _, _, ok in ranked if ok]
    assert "blk" not in allowed and len(allowed) == 2          # blocked one used an active slot but can't post


def test_creator_bonus_is_shrunk_for_few_posts():
    eng = {"steady": [100.0] * 30, "lucky": [5000.0], "flop": [1.0] * 30}
    b = creator_bonus(eng)
    assert b["steady"] > b["flop"]
    assert abs(b["lucky"]) < 1.0                                # one viral post barely moves the ranking
    assert creator_bonus({"x": [1.0] * 5}) == {}                # not enough data yet: no adjustment


def test_peak_slot_skips_taken_and_past_slots():
    after = datetime(2026, 11, 21, 13, 30, tzinfo=timezone.utc)
    taken = {datetime(2026, 11, 21, 15, tzinfo=timezone.utc)}
    assert next_peak_slot(after, taken) == datetime(2026, 11, 21, 18, tzinfo=timezone.utc)
