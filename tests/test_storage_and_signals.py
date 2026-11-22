import os
import re
import time

import numpy as np

from clip_signals.signals import energy_bonus, heat_bonus, snap
from storage.dedupe import dedupe, same_file
from storage.guardian import Dirs, State, candidates

vid = lambda name: (re.findall(r"\[([A-Za-z0-9_-]{11})\]", name) or [None])[-1]


def _file(p, size=10, hours_old=0.0):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    t = time.time() - hours_old * 3600
    os.utime(p, (t, t))
    return p


def test_dedupe_links_exact_duplicates(tmp_path):
    up = _file(tmp_path / "uploads" / "abc123-Show [AAAAAAAAAAA].mp4", 1000)
    dl = _file(tmp_path / "downloads" / "Creator" / "Show [AAAAAAAAAAA].mp4", 1000)
    _file(tmp_path / "downloads" / "Creator" / "Other [BBBBBBBBBBB].mp4", 999)
    assert dedupe(tmp_path / "uploads", [tmp_path / "downloads"], apply=True) == 1000
    assert same_file(up, dl) and dl.read_bytes() == b"x" * 1000
    assert dedupe(tmp_path / "uploads", [tmp_path / "downloads"], apply=True) == 0   # idempotent


def test_guardian_rules(tmp_path):
    d = Dirs(work=tmp_path / "work", uploads=tmp_path / "uploads", downloads=tmp_path / "downloads",
             clips=[tmp_path / "clips"], never=[tmp_path / "data"])
    done = _file(d.uploads / "j1-A [AAAAAAAAAAA].mp4", hours_old=1)
    running = _file(d.uploads / "j2-B [BBBBBBBBBBB].mp4", hours_old=5)
    fresh_done = _file(d.uploads / "j3-C [CCCCCCCCCCC].mp4", hours_old=0.1)
    src_done = _file(d.downloads / "A [AAAAAAAAAAA].mp4", hours_old=3)
    src_open = _file(d.downloads / "B [BBBBBBBBBBB].mp4", hours_old=30)
    partial = _file(d.downloads / "D [DDDDDDDDDDD].mp4.part", hours_old=4)
    scratch = _file(d.work / "seg.mp4", hours_old=4)
    st = State(job_done_sources={str(done.resolve()).lower(), str(fresh_done.resolve()).lower()},
               job_active_sources={str(running.resolve()).lower()},
               finished_video_ids={"AAAAAAAAAAA"})
    out = {p.name: rule for rule, p in candidates(d, st, emergency=False, video_id=vid)}
    assert out[done.name].startswith("R2") and out[src_done.name].startswith("R3")
    assert out[partial.name].startswith("R7") and out[scratch.name].startswith("R1")
    assert running.name not in out and fresh_done.name not in out and src_open.name not in out


def test_heatmap_bonus_rewards_the_most_replayed_moment():
    heat = [{"start_time": i, "end_time": i + 1, "value": 1.0 if i == 50 else 0.2} for i in range(100)]
    assert heat_bonus({"start": 45, "end": 60}, heat) > 3
    assert heat_bonus({"start": 0, "end": 10}, heat) <= 0


def test_energy_bonus_for_loud_peak():
    prof = np.full(200, 40.0) + np.random.default_rng(0).normal(0, 1, 200)
    prof[100:104] = 60
    assert energy_bonus({"start": 48, "end": 55}, prof) > 2
    assert energy_bonus({"start": 10, "end": 20}, prof) == 0


def test_snap_to_cuts():
    c = snap({"start": 10.0, "end": 30.0}, s_cuts=[9.2, 11.0], e_cuts=[29.0, 30.6], duration=60)
    assert (c["start"], c["end"], c["length"]) == (9.2, 30.6, 21.4)


from clip_signals.ads import ad_text, video_id


def test_ad_reads_are_detected_but_gameplay_is_not():
    assert ad_text("This video is sponsored by a game, use code CLIPS for a bonus")
    assert ad_text("These are high-quality plushies of our characters")
    assert ad_text("Yo, this is a nice jewelry store, $400 in the bag") is None
    assert ad_text("you don't know what you get yourself into") is None


def test_video_id_from_downloaded_filename():
    assert video_id("Some Title [abcdefghijk].mp4") == "abcdefghijk"
    assert video_id("no id here.mp4") is None
