"""NO_ADS_V1 (2026-11-22): never clip a creator's sponsor read, merch plug or app promo.

Two independent checks, applied to every candidate moment before rendering:
  1. SponsorBlock (free community database of sponsor/self-promo segments, keyed by the public YouTube video ID
     in the downloaded file's name '[xxxxxxxxxxx]'): a clip overlapping a segment by >= 25 % is dropped.
  2. The clip's own words: one unmistakable ad phrase ('sponsored by', 'use code', 'link in the description',
     'pre-order') or two softer ones ('plushies', 'merch', 'store', '$29') mark it as an ad.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

SPONSORBLOCK = "https://sponsor.ajay.app/api/skipSegments"
CATEGORIES = ["sponsor", "selfpromo", "interaction"]

STRONG = re.compile(
    r"sponsored by|today'?s sponsor|this (video|episode) is (sponsored|brought)|thanks? to \w+ for sponsoring|"
    r"brought to you by|in partnership with|use (my |the )?code|promo code|discount code|coupon|"
    r"\bgo to [\w.-]+\.(com|io|gg|co)\b|check out [\w.-]+\.(com|io|gg|co)\b|"
    r"pre-?order|\bmerch\b|\bget yours\b(?!elf)|limited edition|free trial|sign up (now|today|for free)|first \d+ (people|users)|"
    r"free shipping|\d+\s?% off|available (now|today) (at|on|in)", re.I)
SOFT = re.compile(
    r"\bplush(ie|ies|y)?\b|\bhoodies?\b|\bt-?shirts?\b|\b(my|our) (online )?(store|shop)\b|play store|app store|"
    r"\border (now|today|yours)\b|link in (the |my )?(description|bio)|link (is )?(down )?below|"
    r"\bdownload\b|\bsubscription\b|high[- ]quality|\bcollectibles?\b|\bprice\b|\bwebsite\b|"
    r"\bsponsor\b|\bpartnered\b|\bapp\b|\bvpn\b|\bproducts?\b", re.I)


def video_id(media_path: str | None) -> str | None:
    m = re.search(r"\[([\w-]{11})\]", str(media_path or ""))
    return m.group(1) if m else None


def sponsor_segments(vid: str | None) -> list[tuple[float, float]]:
    if not vid:
        return []
    q = urllib.parse.urlencode({"videoID": vid, "categories": json.dumps(CATEGORIES)})
    try:
        with urllib.request.urlopen(f"{SPONSORBLOCK}?{q}", timeout=8) as r:
            return [(float(s["segment"][0]), float(s["segment"][1])) for s in json.load(r)]
    except Exception:          # 404 = no segments submitted; offline = rely on the transcript check
        return []


def ad_text(text: str) -> str | None:
    strong = STRONG.findall(text or "")
    if strong:
        return "ad phrase"
    soft = {m.group(0).lower() for m in SOFT.finditer(text or "")}
    return "ad words: " + ", ".join(sorted(soft)) if len(soft) >= 2 else None


def clip_text(words: list[dict], s: float, e: float) -> str:
    return " ".join(str(w.get("word", w.get("text", ""))) for w in words
                    if float(w.get("start", 0)) >= s - 0.5 and float(w.get("end", 0)) <= e + 0.5)


def filter_ads(clips: list[dict], transcript: dict, media_path: str | None, log=print, use_sponsorblock=True) -> list[dict]:
    segs = sponsor_segments(video_id(media_path)) if use_sponsorblock else []
    words = transcript.get("words") or []
    keep = []
    for c in clips:
        s, e = float(c["start"]), float(c["end"])
        overlap = sum(max(0.0, min(e, b) - max(s, a)) for a, b in segs)
        why = (f"SponsorBlock segment ({overlap:.0f}s)" if overlap >= 0.25 * max(e - s, 1)
               else ad_text(clip_text(words, s, e)))
        if why:
            log(f"NO_ADS_V1: dropped '{c.get('title', '')}' {s:.0f}-{e:.0f}s ({why})")
        else:
            keep.append(c)
    return keep
