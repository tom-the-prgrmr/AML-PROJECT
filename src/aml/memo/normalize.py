"""Memo normalisation and the deterministic rule layer for instruction-like text. Pure.

Memos are classified per normalised key, not per transaction: almost all the variety in the data is
a reference number, so replacing digit runs by ``#`` turns tens of thousands of memos into a few
dozen keys. The rules run before any model call, so known injection text never reaches the LLM.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Version of normalisation + rules + prompt (with its few-shot examples) + output schema.
# Change any of them and this must change: labels of another version are never mixed in.
MEMO_VERSION = "memo/v1"

# Applied in this order to the normalised text with the accents removed (English and Vietnamese).
INJECTION_PATTERNS: tuple[str, ...] = (
    r"(ignore|disregard|forget) (all |any )?(the )?(previous|prior|above|earlier) "
    r"(instructions?|rules|prompts)",
    r"bo qua (moi |tat ca )?(cac )?(huong dan|chi dan|quy tac)",
    r"(^|[.;:!?] ?)(system|assistant|developer) ?:",
    r"(you are now|admin mode|developer mode)",
    r"(do not|don't|never|khong|dung) (raise|report|flag|bao cao|canh bao)",
    r"(mark|label|danh dau|coi|xem) .{0,40}(clean|safe|sach|hop le)",
    r"(clear|close|approve|whitelist)(ed)? (all |this |the )?"
    r"(alerts?|transactions?|accounts?|cases?)",
)
_COMPILED = tuple(re.compile(p) for p in INJECTION_PATTERNS)
_SPACES = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_JOINERS = re.compile(r"[-_.,]+")  # ignore-previous, ignore, previous: read as word breaks


def normalize_memo(raw: str | None, max_chars: int = 200) -> str:
    """The key text of a memo; ``""`` when there is no memo.

    Unicode NFC, runs of whitespace become one space, lower case, each run of digits becomes one
    ``#``, cut at ``max_chars``. Vietnamese accents are kept (the model reads both forms).
    """
    if not isinstance(raw, str):  # NULL arrives as None or NaN
        return ""
    text = _SPACES.sub(" ", unicodedata.normalize("NFC", raw)).strip().lower()
    return _DIGITS.sub("#", text)[:max_chars]


def memo_key(norm: str) -> str:
    """First 32 hex characters of the SHA-256 of the normalised memo (UTF-8)."""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def strip_accents(text: str) -> str:
    """``đánh dấu`` -> ``danh dau``: the rules are written without accents."""
    decomposed = unicodedata.normalize("NFD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return plain.replace("đ", "d").replace("Đ", "D")


def _variants(norm: str) -> tuple[str, ...]:
    """The texts the rules are matched on, so disguised spelling cannot slip past them.

    NFKC folds full-width letters; invisible format characters (zero-width space, soft hyphen) are
    dropped in one variant and read as a space in the other; a second pair also reads ``-_.,`` as
    a space. Only the rules see these texts: the memo key is built from ``norm`` itself.
    """
    folded = unicodedata.normalize("NFKC", norm).lower()
    dropped = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    spaced = "".join(" " if unicodedata.category(ch) == "Cf" else ch for ch in folded)
    texts = []
    for text in (dropped, spaced):
        texts.append(text)
        texts.append(_JOINERS.sub(" ", text))
    return tuple(_SPACES.sub(" ", strip_accents(t)).strip() for t in texts)


def injection_pattern(norm: str) -> int:
    """Number (from 1) of the first pattern that matches the normalised memo; 0 when none does."""
    texts = _variants(norm)
    for number, pattern in enumerate(_COMPILED, start=1):
        if any(pattern.search(text) for text in texts):
            return number
    return 0
