from __future__ import annotations

import html
import re
import unicodedata

_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_WS = re.compile(r"\s+")
_BOILERPLATE = re.compile(
    r"\b(?:subscribe|unsubscribe|sign\s*up|cookie\s*(?:settings|consent)|"
    r"advertisement|sponsored|follow\s+us|read\s+more|privacy\s+policy|"
    r"terms\s+of\s+service|all\s+rights\s+reserved)\b", re.I
)


def clean_text(text: str | None) -> str:
    """Create a searchable surface without changing the stored source quote."""
    value = unicodedata.normalize("NFC", text or "")
    value = html.unescape(value).replace("\xa0", " ")
    value = value.replace("\u2018", "'").replace("\u2019", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    value = _LINK.sub(r"\1", value)
    value = _TAG.sub(" ", value)
    value = _URL.sub(" ", value)
    value = re.sub(r"(^|\s)#{1,6}\s*", r"\1", value)
    value = value.replace("`", "").replace("*", "").replace("_", " ")
    return _WS.sub(" ", value).strip()


def clean_title(text: str | None, *, max_words: int = 15) -> str:
    value = clean_text(text)
    if not value:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", value)[0]
    sentence = re.sub(r"^(?:breaking|update|alert|exclusive)\s*[:\-]\s*", "", sentence, flags=re.I)
    words = sentence.strip(" \t.,;:!?\"'").split()
    if len(words) > max_words:
        return " ".join(words[:max_words]).rstrip(".,;:!? ") + "..."
    return " ".join(words)


def is_boilerplate(text: str | None, *, max_hits: int = 1) -> bool:
    value = clean_text(text)
    return not value or len(_BOILERPLATE.findall(value)) >= max_hits
