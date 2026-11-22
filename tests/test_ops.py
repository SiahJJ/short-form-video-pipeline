import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("notifier", Path(__file__).parents[1] / "ops" / "notifier.py")
notifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notifier)


def test_alerts_are_edge_triggered(tmp_path, monkeypatch):
    monkeypatch.setattr(notifier, "STATE", tmp_path / "state.json")
    sent = []
    send = lambda s, b: sent.append(s)
    assert notifier.alert_once("disk", True, "Disk low", "", send)      # condition starts -> email
    assert not notifier.alert_once("disk", True, "Disk low", "", send)  # still true -> quiet
    notifier.alert_once("disk", False, "", "", send)                    # cleared
    assert notifier.alert_once("disk", True, "Disk low", "", send)      # starts again -> email
    assert sent == ["Disk low", "Disk low"]
