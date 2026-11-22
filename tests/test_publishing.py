from datetime import datetime, timedelta, timezone

from publishing.cadence import Cadence
from publishing.ledger import Ledger, PlatformError

T0 = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def test_published_once_then_never_again(tmp_path):
    led = Ledger(tmp_path / "ledger.json")
    calls = []
    up = lambda: calls.append("up") or "vid1"
    assert led.publish("q1", up, lambda v: {"permalink": "x"}) == "published"
    assert led.publish("q1", up, lambda v: {}) == "published"
    assert calls == ["up"]


def test_lost_publish_answer_is_uncertain_and_never_retried(tmp_path):
    led = Ledger(tmp_path / "ledger.json")
    def lost(v):
        raise TimeoutError
    assert led.publish("q1", lambda: "vid1", lost) == "uncertain"
    assert not led.can_attempt("q1")
    assert Ledger(tmp_path / "ledger.json").items["q1"]["status"] == "uncertain"   # persisted


def test_explicit_rejection_is_failed_not_uncertain(tmp_path):
    led = Ledger(tmp_path / "ledger.json")
    def no(v):
        raise PlatformError("OAuthException 190")
    assert led.publish("q1", lambda: "vid1", no) == "failed"


def test_failure_before_upload_completes_is_retryable(tmp_path):
    led = Ledger(tmp_path / "ledger.json")
    def boom():
        raise ConnectionError
    assert led.publish("q1", boom, lambda v: {}) == "failed_before_publish"
    assert led.can_attempt("q1")
    assert led.publish("q1", lambda: "vid1", lambda v: {}) == "published"


def test_even_pace_spreads_the_daily_cap():
    c = Cadence(cap_24h=50, min_gap_min=5)
    assert c.wait_seconds([T0], T0, local_hour=12, backlog=0) == 29 * 60


def test_end_of_day_burst_uses_short_gap():
    c = Cadence(cap_24h=50)
    wait = c.wait_seconds([T0], T0, local_hour=23, backlog=0)
    assert 5 * 60 <= wait <= 10 * 60


def test_rolling_cap_beats_the_burst():
    c = Cadence(cap_24h=3, even_pace=False)                   # isolate the rolling cap
    posts = [T0 - timedelta(hours=h) for h in (20, 10, 1)]
    wait = c.wait_seconds(posts, T0, local_hour=23, backlog=10)
    assert wait == 4 * 3600                                   # oldest of the last 3 ages out at +4h
