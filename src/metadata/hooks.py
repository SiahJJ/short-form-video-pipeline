"""Bilingual caption hooks from a local LLM - with a grounding check so the model can't add facts.

A small local model (Qwen3 8B via Ollama) writes a punchy first line in English, plus Spanish when the source
is Spanish. Small models embellish: for a news clip one added a claim about who was in charge that the
source never made (and that was false). So every longer word of the Spanish hook must stem-match the source title/transcript,
otherwise the hook is regenerated at a lower temperature, and finally dropped. No hook beats a false one.
"""
from __future__ import annotations

import json
import re
import urllib.request

from .hashtags import deaccent, words

OLLAMA = "http://127.0.0.1:11434/api/chat"
ES_WORDS = {"el", "la", "los", "las", "de", "del", "en", "y", "que", "por", "para", "con", "una", "un", "es",
            "su", "al", "lo", "como", "mas", "pero", "sus", "le", "ya", "o", "este", "esta", "porque"}
EN_WORDS = {"the", "and", "is", "of", "to", "you", "that", "this", "with", "for", "what", "it"}
# headline words a hook may use even when the source doesn't (verbs / connectors, never facts)
ES_HOOK_OK = {"impactante", "increible", "urgente", "momento", "ahora", "mientras", "durante", "despues",
              "contra", "dentro", "frente", "nuevo", "nueva", "mundo", "nadie", "nunca", "mira", "revela",
              "muestra", "responde", "anuncia", "confirma", "ordena", "lanza", "ataca", "atacan"}


def is_spanish(title: str, transcript: str = "") -> bool:
    text = f"{title} {transcript[:1500]}".lower()
    ws = re.findall(r"[a-záéíóúñü]+", text)
    if not ws:
        return False
    es = sum(deaccent(w) in ES_WORDS for w in ws) + 3 * len(re.findall(r"[ñ¿¡]|ción\b", text))
    en = sum(w in EN_WORDS for w in ws)
    return es > max(3, 1.5 * en) or bool(re.search(r"[ÁÉÍÓÚÑ¿¡]|CIÓN\b|ción\b", title) and en < 3)


def grounded(hook: str, source: str) -> bool:
    """Every word of 6+ letters must appear in the source, share a 5-letter stem with it (bombardea ~
    bombardeo), or be an allowed headline word. Catches 'pandero' (tambourine) for 'pandillero' (gang member)."""
    src = set(words(source))
    stems = {w[:5] for w in src if len(w) >= 5}
    return all(w in src or w in ES_HOOK_OK or w[:5] in stems for w in words(hook) if len(w) >= 6)


def valid(hook: str) -> bool:
    return 12 <= len(hook) <= 110 and "#" not in hook and "http" not in hook


def prompt(creator: str, title: str, transcript: str, spanish: bool) -> str:
    return (
        "Write the opening line of an Instagram Reel caption for this clip. It must make people stop scrolling: "
        "concrete, urgent, specific (who/what/where), present tense. Restate ONLY what TITLE or TRANSCRIPT say, "
        "just punchier - do NOT add context, causes, consequences, roles or adjectives that are not there; never "
        "add names, numbers or places. Max 90 characters, no hashtags, no quotation marks, may start with one "
        "fitting emoji.\n"
        + ('Give it in English AND in natural Spanish (same meaning). hook_en must be fully English - translate '
           'every Spanish word; only names stay as they are. JSON only: {"hook_en": "...", "hook_es": "..."}\n'
           if spanish else 'English only. JSON only: {"hook_en": "..."}\n')
        + f"\nCREATOR: {creator}\nTITLE: {title}\nTRANSCRIPT (excerpt): {transcript[:1200]}")


def make_hooks(creator: str, title: str, transcript: str, model: str = "qwen3:8b", ask=None):
    """Returns (hook_en, hook_es or '') or None. `ask(prompt, temperature) -> dict` is injectable for tests."""
    spanish = is_spanish(title, transcript)
    ask = ask or (lambda p, t: _ollama(p, t, model))
    source = f"{creator} {title} {transcript}"
    for temp in (0.4, 0.2, 0.1):
        try:
            out = ask(prompt(creator, title, transcript, spanish), temp)
        except Exception:
            return None
        en = str(out.get("hook_en") or "").strip().strip('"')
        es = str(out.get("hook_es") or "").strip().strip('"')
        if valid(en) and (not spanish or (valid(es) and grounded(es, source))):
            return en, (es if spanish else "")
    return None


def _ollama(p: str, temperature: float, model: str) -> dict:
    body = json.dumps({"model": model, "stream": False, "think": False, "format": "json",
                       "options": {"temperature": temperature, "num_ctx": 4096},
                       "messages": [{"role": "user", "content": p}]}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(json.load(r)["message"]["content"])
