"""Hashtag hygiene and niche detection for short-form video captions.

Tags come from a candidate pool (titles, YouTube tags, transcript, trends). These rules turn raw phrases into
tags people actually search, and guarantee each community's own tags:

* accent folding        'PERÚ'             -> #Peru         (naive [A-Za-z] stripping gave #Per)
* franchise stands alone 'GTA4 Retrospective' -> rejected; #GTA4 stays its own tag
* no dangling phrases   'NPCs Crash Into'  -> rejected
* niche guarantees      news               -> #BreakingNews always; Spanish news also #Noticias
* family tags           #GTA4 present      -> #GTA added
"""
from __future__ import annotations

import re
import unicodedata

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "is", "it", "this",
        "that", "my", "your", "i", "you", "we", "he", "she", "they", "be", "was", "are"}
DANGLING = {"into", "onto", "from", "about", "over", "after", "before", "vs", "when", "how", "why", "what"}
FILLER = {"today", "latest", "now", "new", "best", "top", "video", "videos", "official", "full", "live"}
FRANCHISE = re.compile(r"(?:gta|nba|nfl|ufc|wwe|aew|mlb|nhl|fifa|cod|mw)\d*|[a-z]{2,4}\d+")
UPPER = {"nba", "nfl", "ufc", "mma", "wwe", "aew", "atp", "wta", "gta", "ai", "spy", "qqq", "btc"}

NICHES: dict[str, tuple[list[str], list[str]]] = {
    # name: (evidence keywords, community tags in priority order)
    "news": (["breaking", "press conference", "election", "president", "government", "war", "airstrike",
              "attack", "military", "protest", "noticias", "ultima hora", "bombardeo", "presidente",
              "gobierno", "guerra", "ataque", "militar"],
             ["BreakingNews", "News", "WorldNews", "CurrentEvents", "Politics"]),
    "gaming": (["gameplay", "gaming", "fortnite", "minecraft", "gta", "call of duty", "twitch", "streamer",
                "speedrun", "playstation", "xbox", "nintendo"],
               ["Gaming", "Gamer", "GamingClips", "Gameplay", "VideoGames"]),
    "tennis": (["tennis", "atp", "wta", "wimbledon", "grand slam", "serve"],
               ["Tennis", "ATP", "TennisLife", "TennisHighlights"]),
    "trading": (["day trading", "stock market", "stocks", "options", "spy", "qqq", "nasdaq", "futures"],
                ["DayTrading", "StockMarket", "Stocks", "Trading", "Investing"]),
    "podcast": (["podcast", "episode", "interview"], ["Podcast", "PodcastClips", "Interview"]),
}
GENERIC = {t.lower() for _, tags in NICHES.values() for t in tags}


def deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", deaccent(s).lower())


def pretty(w: str) -> str:
    lw = w.lower()
    if lw in UPPER or (w.isupper() and (len(w) <= 3 or any(c.isdigit() for c in w))):
        return w.upper()
    return w[:1].upper() + w[1:].lower() if w.isupper() or w.islower() else w


def to_tag(phrase: str) -> str | None:
    """'Grand Theft Auto' -> 'GrandTheftAuto'; None when the phrase would make a bad tag."""
    phrase = re.sub(r"['’](s|t|re|ll|ve|d|m)\b", "", deaccent(phrase), flags=re.I)
    ws = re.findall(r"[A-Za-z0-9]+", phrase)
    if not ws or len(ws) > 3:
        return None
    lws = [w.lower() for w in ws]
    if any(w in FILLER for w in lws) or all(w in STOP for w in lws):
        return None
    if len(ws) > 1 and any(FRANCHISE.fullmatch(w) for w in lws):
        return None                                   # #GTA4Retrospective -> keep #GTA4 on its own
    if lws[-1] in STOP or lws[-1] in DANGLING:
        return None                                   # #NPCsCrashInto
    tag = "".join(pretty(w) for w in ws)
    return tag if 3 <= len(tag) <= 24 and not tag.isdigit() else None


def detect_niche(title: str, tags: list[str], transcript: str = "") -> str | None:
    """Title/tags weigh 3, transcript 0.5; the title or tags must mention the niche at least once."""
    norm = lambda x: " " + " ".join(words(x)) + " "
    strong, spoken = norm(f"{title} {' '.join(tags)}"), norm(transcript[:700])
    best, best_score = None, 0.0
    for name, (keys, _) in NICHES.items():
        hits = lambda t: sum(t.count(f" {' '.join(words(k))} ") for k in keys)
        hs = hits(strong)
        if hs:
            score = 3 * hs + 0.5 * hits(spoken)
            if score > best_score:
                best, best_score = name, score
    return best if best_score >= 3 else None


def guarantee(tags: list[str], cap: int, niche: str | None, spanish: bool, protected: set[str]) -> list[str]:
    """Add must-have tags, replacing generic community tags first and never a protected (creator/person) tag."""
    tags = list(tags)
    must = []
    if niche == "news":
        must += ["BreakingNews"] + (["Noticias"] if spanish else [])
    if any(re.fullmatch(r"GTA\d+|GTA[A-Z]\w+", t) for t in tags):
        must.append("GTA")
    low = lambda t: t.lower()
    for m in must:
        if any(low(t) == low(m) for t in tags):
            continue
        if len(tags) >= cap:
            keep = lambda t: low(t) in {low(p) for p in protected} or t in must
            drop = next((t for t in reversed(tags) if not keep(t) and low(t) in GENERIC), None) \
                or next((t for t in reversed(tags) if not keep(t)), None)
            if drop:
                tags.remove(drop)
        if len(tags) < cap:
            tags.append(m)
    return tags


# ---- topic tags and creator popularity (TOPIC_TAGS_V1) ----
POPULAR_SUBS = 5_000_000
HYPE = {"ultimate", "epic", "insane", "crazy", "chaos", "moment", "moments", "unleashed", "drama", "power",
        "amazing", "wild", "shocking", "reacts", "reaction", "story", "secret", "truth", "season", "trailer",
        "full", "film", "official", "speaks", "talks", "reveals", "explained", "challenge", "tried", "beat"}
DEMONYM = {"african": "Africa", "american": "America", "mexican": "Mexico", "japanese": "Japan",
           "brazilian": "Brazil", "indian": "India", "canadian": "Canada", "french": "France"}


def topic_tags(source_title: str, clip_title: str, transcript: str, description: str = "") -> list[tuple[str, int]]:
    """What the clip is ABOUT, as (tag, score). A title word counts when the clip says it (same 5-letter stem:
    'African' ~ 'Africa'); the uploader's description is weaker evidence; title-only words score lowest."""
    spoken = {w[:5] for w in words(transcript) if len(w) >= 4}
    described = {w[:5] for w in words(description) if len(w) >= 4}
    out: dict[str, int] = {}
    for src, pts in ((source_title, 40), (clip_title, 36)):
        for w in re.findall(r"[A-Za-z]+", deaccent(src)):
            lw = w.lower()
            if len(lw) < 4 or lw in STOP or lw in FILLER or lw in HYPE:
                continue
            bonus = 0 if lw[:5] in spoken else -8 if lw[:5] in described else -14
            tag = to_tag(DEMONYM.get(lw, lw.capitalize() if w.isupper() else w))
            if tag:
                out[tag] = max(out.get(tag, 0), pts + bonus)
    return sorted(out.items(), key=lambda kv: -kv[1])


def keep_creator_tag(subscribers: int | None, niche: str | None, known_anchor: bool = False) -> bool:
    """A creator tag earns one of five slots only if people search for that creator: very large channels, or
    news anchors/channels (news viewers search the outlet). Small channels give the slot to the topic."""
    if niche == "news":
        return known_anchor or bool(subscribers and subscribers >= 250_000)
    return bool(subscribers and subscribers >= POPULAR_SUBS)


def creator_niche(fixed: str | None, source_title: str, clip_title: str) -> str | None:
    """A creator's usual niche applies only when this clip's own titles mention it: a gaming streamer's
    documentary about a country gets that country's tags, not #Gaming #Gamer."""
    if not fixed:
        return None
    own = " " + " ".join(words(f"{source_title} {clip_title}")) + " "
    return fixed if any(f" {' '.join(words(k))} " in own for k in NICHES[fixed][0]) else None


def merge_names(tags: list[str], texts: list[str]) -> list[str]:
    """#Jane #Smith -> #JaneSmith when the pair appears side by side at least twice in the titles/description."""
    seq = words(" ".join(texts))
    pairs: dict[tuple[str, str], int] = {}
    for a, b in zip(seq, seq[1:]):
        pairs[(a, b)] = pairs.get((a, b), 0) + 1
    out = list(tags)
    for a in list(out):
        for b in list(out):
            if a in out and b in out and a != b and pairs.get((a.lower(), b.lower()), 0) >= 2 \
                    and re.fullmatch(r"[A-Z][a-z]+", a) and re.fullmatch(r"[A-Z][a-z]+", b):
                out[out.index(a)] = a + b
                out.remove(b)
    return out
