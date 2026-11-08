"""Local, deterministic, privacy-conscious long-term fact candidates.

Only *user-authored* messages can yield automatic memories. No model output,
webpage, file content or tool response is treated as a personal fact.
The extractor intentionally prefers missing a fact to inventing one.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

STOPWORDS = frozenset(
    "aber alle als also an auf aus bei bin bis das dass dem den der des die dies "
    "doch du ein eine einem einen einer er es für fuer habe haben hier ich im in "
    "ist ja kann keine mein meine meinen meiner mit nach nicht noch nur oder "
    "schon sein sich sie so soll und uns vom von was wenn wer wie wir wird zu "
    "zum zur the this your and are with from for that".split()
)
SENSITIVE = re.compile(
    r"(?i)\b(?:passwort|password|api[\s_-]?key|secret|bearer|access[\s_-]?token|"
    r"auth[\s_-]?token|private[\s_-]?key|otp|2fa|sicherheitscode|iban|bic|"
    r"kreditkarte|kartennummer|pin[\s_-]?code|"
    r"diagnose|krankheit|erkrankung|medikament|symptom|therapie|"
    r"sexuell|sexualität|religion|politische[\s_-]?partei|"
    r"polizeianzeige|strafregister)\b"
)
PRIVATE_STRING = re.compile(
    r"(?i)(?:https?://\S*[/=](?:token|key|secret)=|"
    r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{16,})\b)"
)
TRIGGERS = (
    re.compile(r"(?i)^\s*(?:bitte\s+)?(?:merke?\s+dir|merk\s+dir|behalte\s+(?:das|dies)\s+im\s+kopf)\s*[:,]?\s*(?:dass\s+)?(.+)$"),
    re.compile(r"(?i)^\s*(?:für\s+später\s*:)\s*(.+)$"),
)
AUTO = re.compile(
    r"(?i)\b(?:ich\s+(?:bevorzuge|mag|möchte|will|nutze|verwende|arbeite\s+mit)|"
    r"mein(?:e|em|en|er)?\s+(?:projekt|ziel|präferenz|regel|standard)|"
    r"(?:für|in|bei)\s+(?:mein(?:e|em|en)?\s+)?projekt\s+|"
    r"(?:ab\s+jetzt|von\s+nun\s+an|künftig|zukünftig|stattdessen|nicht\s+mehr|sondern))\b"
)
IGNORE = re.compile(
    r"(?i)^\s*(?:was|warum|wie|wann|wer|wo|kannst\s+du|könntest\s+du|"
    r"würdest\s+du|angenommen|zum\s+beispiel|stell\s+dir\s+vor)\b"
)
PROJECT = re.compile(
    r"(?i)\b(?:projekt|project)\s+([A-Za-z][A-Za-z0-9_-]{2,40})\b"
)
KNOWN_PROJECT = re.compile(r"(?i)\b(sytox|maincw|tmnt)\b")
CORRECTION = re.compile(
    r"(?i)\b(?:nicht\s+mehr|stattdessen|sondern|ab\s+jetzt|von\s+nun\s+an|"
    r"künftig|zukünftig|korrektur)\b"
)
SLOTS = (
    ("theme", r"\b(?:farbe|farbthema|farbschema|designfarbe|dunkelrot|schwarz|blau|rot)\b"),
    ("language", r"\b(?:programmiersprache|spracheinstellung|sprachstil|hochdeutsch)\b"),
    ("voice", r"\b(?:stimme|sprachstimme|aussprache|akzent)\b"),
    ("engine", r"\b(?:unreal\s+engine|godot|unity|engine)\b"),
    ("platform", r"\b(?:betriebssystem|windows|linux|android|ios|plattform)\b"),
    ("interface", r"\b(?:oberfläche|interface|clickgui|layout)\b"),
)


def tokens(text: str) -> list[str]:
    """Normalize German umlauts and retain distinctive words for retrieval."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
    words = re.findall(r"[^\W_]{3,}", normalized, flags=re.UNICODE)
    result = []
    for term in words[:120]:
        if term not in STOPWORDS and term not in result:
            result.append(term)
    return result


def project_scopes(text: str) -> set[str]:
    """Only explicit project names; generic project wording is not an identity."""
    excluded = {"ist", "hat", "soll", "mit", "für", "fuer", "eine", "mein",
                "bevorzuge", "verwende", "nutze", "möchte", "moechte", "brauche",
                "wird", "weiter", "fortsetzen", "bitte", "nicht", "keine"}
    names = [match.group(1).casefold() for match in PROJECT.finditer(str(text or ""))]
    names += [match.group(1).casefold() for match in KNOWN_PROJECT.finditer(str(text or ""))]
    return {"project:" + name for name in names if name not in excluded}


def memory_topics(text: str) -> set[str]:
    """Use the same conservative fact topics when a question uses different words."""
    text = str(text or "")
    result = {name for name, pattern in SLOTS if re.search(pattern, text, re.IGNORECASE)}
    if re.search(r'\b(?:lieblingsfarbe\w*|farb\w*|design)\b', text, re.IGNORECASE):
        result.add('theme')
    if re.search(r'\b(?:sprache|sprachstil|ansprache|formulierung)\b', text, re.IGNORECASE):
        result.add('language')
    if re.search(r'\b(?:schrift(?:größe|grösse|groesse|art)?|font\w*|typograf\w*)\b', text, re.IGNORECASE):
        result.add('typography')
    return result


def _scope(sentence: str) -> str:
    scopes = project_scopes(sentence)
    # Preserve first-mentioned scope for facts mentioning multiple projects.
    for match in list(PROJECT.finditer(sentence)) + list(KNOWN_PROJECT.finditer(sentence)):
        scope = "project:" + match.group(1).casefold()
        if scope in scopes:
            return scope
    return "global"


def _slot(sentence: str, scope: str) -> str:
    for name, pattern in SLOTS:
        if re.search(pattern, sentence, re.IGNORECASE):
            return name
    # Don't overwrite unrelated facts just because both mention a project.
    fingerprint = hashlib.sha256(sentence.casefold().encode("utf-8")).hexdigest()[:18]
    return "note:" + fingerprint


def extract_facts(message: str) -> list[dict]:
    """Return up to three conservative facts, without executing or using an LLM."""
    text = str(message or "").strip()
    if not text or len(text) > 4000:
        return []
    output = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence = re.sub(r"\s+", " ", sentence).strip(" \t,;:")
        if not 8 <= len(sentence) <= 350:
            continue
        if SENSITIVE.search(sentence) or PRIVATE_STRING.search(sentence):
            continue
        explicit = False
        fact = sentence
        for trigger in TRIGGERS:
            match = trigger.match(sentence)
            if match:
                explicit, fact = True, match.group(1).strip()
                break
        if IGNORE.search(fact) or '?' in fact:
            continue
        if not explicit and not AUTO.search(fact):
            continue
        if len(tokens(fact)) < 2:
            continue
        scope = _scope(fact)
        slot = _slot(fact, scope)
        output.append({
            "scope": scope, "fact_key": slot, "content": fact[:350],
            "kind": "correction" if CORRECTION.search(fact) else ("explicit" if explicit else "automatic")
        })
        if len(output) == 3:
            break
    return output


def is_continuation_request(text: str) -> bool:
    return bool(re.search(
        r"(?i)\b(?:weitermachen|weitermachen|weiterarbeiten|fortsetzen|"
        r"letztes?\s+projekt|vorherig\w*\s+projekt|"
        r"wo\s+waren\s+wir|wo\s+sind\s+wir\s+stehen\s+geblieben|"
        r"arbeite\s+weiter|projekt\s+weiter)\b", str(text or "")
    ))
