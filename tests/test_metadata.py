from metadata.hashtags import deaccent, detect_niche, guarantee, to_tag
from metadata.hooks import grounded, is_spanish, make_hooks

SRC = "ATAQUE EN PERÚ: GOBIERNO BOMBARDEA MANSIÓN DE PANDILLERO"


def test_accents_are_folded_not_dropped():
    assert deaccent("PERÚ") == "PERU"
    assert to_tag("Perú") == "Peru"


def test_franchise_is_never_glued_to_other_words():
    assert to_tag("GTA4 Retrospective") is None
    assert to_tag("GTA6") == "GTA6"


def test_dangling_and_filler_phrases_rejected():
    assert to_tag("NPCs Crash Into") is None
    assert to_tag("best video") is None
    assert to_tag("Grand Theft Auto") == "GrandTheftAuto"


def test_niche_needs_title_evidence():
    assert detect_niche(SRC, []) == "news"
    assert detect_niche("Funny cat compilation", [], "the war of the cats") is None   # transcript alone isn't enough


def test_news_guarantees_breakingnews_and_drops_generic_first():
    tags = ["NewsAnchor", "Politics", "CurrentEvents", "Peru", "Gangs"]
    out = guarantee(tags, 5, "news", spanish=True, protected={"NewsAnchor"})
    assert out[:1] == ["NewsAnchor"] and "Peru" in out and "Gangs" in out
    assert "BreakingNews" in out and "Noticias" in out


def test_gta_family_tag_added():
    assert "GTA" in guarantee(["Reviewer", "GTA4"], 5, "gaming", False, set())


def test_spanish_detection():
    assert is_spanish(SRC)
    assert not is_spanish("I Tried Becoming a Pro Baseball Player")


def test_grounding_catches_wrong_word_but_allows_inflection():
    assert grounded("Gobierno bombardea mansión de pandillero en Perú", SRC)
    assert not grounded("Gobierno bombardea la mansión del pandero en Perú", SRC)        # tambourine
    assert not grounded("Gobierno bombardea Perú en medio de violencia creciente", SRC)  # added claim


def test_hooks_retry_then_accept_grounded_answer():
    answers = iter([{"hook_en": "Government bombs a mansion", "hook_es": "Gobierno bombardea mansión del pandero"},
                    {"hook_en": "Government bombs gang leader's mansion in Peru",
                     "hook_es": "Gobierno bombardea mansión de pandillero en Perú"}])
    out = make_hooks("News Anchor", SRC, "", ask=lambda p, t: next(answers))
    assert out == ("Government bombs gang leader's mansion in Peru", "Gobierno bombardea mansión de pandillero en Perú")


def test_hooks_give_up_rather_than_post_a_false_one():
    bad = {"hook_en": "The president rules with an iron fist", "hook_es": "Gobierno controla Perú con violencia creciente"}
    assert make_hooks("X", SRC, "", ask=lambda p, t: bad) is None


from metadata.hashtags import creator_niche, keep_creator_tag, merge_names, topic_tags


def test_topic_words_need_evidence_and_skip_hype():
    tags = dict(topic_tags("THE STORY OF A NATION (Full Film)", "African Freedom Speech: Power of Independence",
                           "the african people wanted freedom and independence"))
    assert {"Africa", "Freedom", "Independence"} <= set(tags)
    assert "Power" not in tags and "Film" not in tags
    assert tags["Africa"] > tags["Speech"]          # spoken beats title-only


def test_creator_tag_only_for_searched_creators():
    assert keep_creator_tag(30_000_000, "gaming")
    assert not keep_creator_tag(40_000, "gaming")
    assert keep_creator_tag(300_000, "news")


def test_usual_niche_must_show_up_in_the_clip():
    assert creator_niche("gaming", "Testing everything in GTA 6", "Drowning rescue") == "gaming"
    assert creator_niche("gaming", "A documentary about a nation", "Freedom speech") is None


def test_split_names_are_merged():
    assert merge_names(["Jane", "Smith", "Tennis"], ["Jane Smith serves", "beat Jane Smith"]) == ["JaneSmith", "Tennis"]
