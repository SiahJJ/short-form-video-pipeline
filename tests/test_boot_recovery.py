import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("boot_recovery", Path(__file__).parents[1] / "ops" / "boot_recovery.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(br, "LOG", tmp_path / "w.log")
    monkeypatch.setattr(br, "FLAG", tmp_path / "flag.json")
    monkeypatch.setattr(br, "CHECK_ONLY", False)


def test_flag_left_by_a_crash_is_removed(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    br.FLAG.write_text(json.dumps({"until": until}))
    monkeypatch.setattr(br, "window_running", lambda kind="": False)   # crashed: no window process
    assert br.clear_stale_flag() and not br.FLAG.exists()


def test_flag_of_a_live_window_is_kept(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    br.FLAG.write_text(json.dumps({"until": until}))
    monkeypatch.setattr(br, "window_running", lambda kind="": True)
    assert not br.clear_stale_flag() and br.FLAG.exists()


def test_interrupted_uploads_are_reported_not_retried(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    ledger = {"a": {"status": "uploading", "started_at": old}, "b": {"status": "published", "started_at": old},
              "c": {"status": "publishing", "started_at": new}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger))
    monkeypatch.setattr(br, "UPLOAD_LEDGERS", [p])
    assert br.report_interrupted_uploads() == ["a"]        # 'c' may still be in progress
    assert json.loads(p.read_text()) == ledger              # nothing changed, nothing re-queued


def test_missed_night_window(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    br.LOG.write_text("2026-01-01T02:30:00 NIGHT WINDOW start\n")
    assert not br.missed_night_window(now=datetime(2026, 1, 1, 9, 0))
    assert br.missed_night_window(now=datetime(2026, 1, 2, 9, 0))
    br.LOG.unlink()
    assert br.missed_night_window()                         # never ran
