import dashboard.helper_server as hs


def _checklist(tmp_path):
    cap = tmp_path / "c1.txt"
    cap.write_text("Great clip #Gaming", encoding="utf-8")
    p = tmp_path / "upload_checklist.csv"
    p.write_text("queue,video_file,caption_file,uploaded\n"
                 f"1,v1.mp4,{cap},inbox 2026-11-21 10:00\n"
                 f"2,v2.mp4,{cap},\n"
                 f"3,v3.mp4,{cap},posted 2026-11-20 09:00\n", encoding="utf-8")
    return p


def test_listing_groups_by_state(tmp_path):
    rows = hs.read_rows(_checklist(tmp_path))
    out = hs.listing(rows)
    assert [i["queue"] for i in out["inbox"]] == ["1"]
    assert [i["queue"] for i in out["waiting"]] == ["2"]
    assert out["inbox"][0]["caption"] == "Great clip #Gaming"


def test_mark_and_undo_round_trip(tmp_path):
    p = _checklist(tmp_path)
    rows = hs.read_rows(p)
    assert hs.mark(rows, {"1"}) == 1
    hs.write_rows(rows, p)
    assert hs.read_rows(p)[0]["uploaded"].startswith("posted")
    hs.mark(rows, {"1"}, undo=True)
    assert rows[0]["uploaded"] == ""


def test_writes_need_allowed_origin_and_custom_header(monkeypatch):
    monkeypatch.setattr(hs, "ALLOWED_ORIGINS", {"https://host.example.ts.net:8443"})
    assert hs.write_allowed("https://host.example.ts.net:8443", "1")
    assert not hs.write_allowed("https://evil.example", "1")              # other site
    assert not hs.write_allowed("https://host.example.ts.net:8443", None)  # simple form post / no header


def test_range_parsing_for_mobile_scrubbing():
    assert hs.parse_range("", 1000) == (0, 999, False)
    assert hs.parse_range("bytes=100-", 1000) == (100, 999, True)
    assert hs.parse_range("bytes=100-199", 1000) == (100, 199, True)
    assert hs.parse_range("bytes=-200", 1000) == (800, 999, True)
    assert hs.parse_range("bytes=900-5000", 1000) == (900, 999, True)
