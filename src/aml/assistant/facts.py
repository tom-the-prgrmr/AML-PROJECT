"""Numbers, dates, verdicts, hedges and account roles found in a sentence, and the ones an evidence
item supports (pure).

The post-check of an answer compares what a sentence states with what the cited evidence holds.
Matching ignores case and Vietnamese diacritics, so ``390 triệu đồng`` and ``390 trieu dong`` are
the same amount (390,000,000).

Only system-built text and values count as support: ``Evidence.text``, ``Evidence.data`` and, for
a knowledge passage, its ``chunk_text``. A memo, an alert reason or a name never supports a number
or a date: a memo that says "transferred 777 million" is not evidence of that amount.

``account_roles`` reads which side of a transfer (``src`` / ``dst``) a sentence gives to an account,
and ``is_speculative`` spots a hedged sentence ("may be", "có thể là"). Both are word lists on
folded text, like ``is_verdict`` (specs/assistant-direction-check.md).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aml.assistant.evidence import Evidence

AMOUNT_FLOOR = 1_000_000  # a bare number this large is read as an amount of VND
SCALES = {
    "nghin": 10**3,
    "ngan": 10**3,
    "thousand": 10**3,
    "k": 10**3,
    "trieu": 10**6,
    "million": 10**6,
    "tr": 10**6,
    "ty": 10**9,
    "ti": 10**9,
    "billion": 10**9,
}
SUPPORTING_FIELD = "chunk_text"  # the only untrusted field that may support a number or a date

_SCALE = r"(?:nghin|ngan|thousand|trieu|million|billion|tr|ty|ti|k)"
_CURRENCY = r"(?:vnd|dong|d)"
_MONEY_WORD = rf"(?:{_SCALE}|{_CURRENCY})(?![a-z])"
_NUMBER = re.compile(
    r"(?<![\w.,\-])"
    r"(?P<num>"
    # grouped with "," or ".", then an optional 1-2 digit fraction with the OTHER separator
    r"\d{1,3}(?P<sep>[.,])\d{3}(?:(?P=sep)\d{3})*(?:(?!(?P=sep))[.,]\d{1,2}(?!\d))?"
    # grouped with spaces: at least two groups, or one group right before a money word
    r"|\d{1,3}(?:[ \xa0]\d{3}){2,}(?:[.,]\d{1,2}(?!\d))?"
    rf"|\d{{1,3}}[ \xa0]\d{{3}}(?=\s*{_MONEY_WORD})"
    r"|\d+[.,]\d{1,2}"  # decimal: an amount only with a scale or a currency word
    r"|\d+)"
    rf"(?:\s*(?P<scale>{_SCALE})(?![a-z]))?"
    rf"(?:\s*(?P<currency>{_CURRENCY})(?![a-z]))?"
    r"(?![a-z0-9]|[.,]\d)"
)
# a money word right after a digit: if no parsed amount covers it, the amount is unreadable
_MONEY_AFTER_DIGIT = re.compile(rf"\d[.,]?[\s\xa0]*(?P<word>{_MONEY_WORD})")
_DATES = (
    (re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"), ("y", "m", "d")),
    (re.compile(r"(?<![\d/])(\d{4})/(\d{1,2})/(\d{1,2})(?![\d/])"), ("y", "m", "d")),
    (re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])"), ("d", "m", "y")),
    (re.compile(r"(?<![\d-])(\d{1,2})-(\d{1,2})-(\d{4})(?![\d-])"), ("d", "m", "y")),
    (re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d|\.\d)"), ("d", "m", "y")),
    (re.compile(r"\bngay (\d{1,2}) thang (\d{1,2}) nam (\d{4})\b"), ("d", "m", "y")),
)
# Phrases that give a verdict on, or an order about, a case (matched on folded text). The gaps
# allow up to 4 words in between: "mark this customer as clean", "clear all alerts".
_GAP = r"(?:\s+\S+){0,4}?\s+"
_VERDICTS = re.compile(
    "|".join(
        (
            rf"\b(?:ignore|disregard){_GAP}(?:instructions?|rules?)\b",
            rf"\bbo qua{_GAP}huong dan\b",
            rf"\bmark{_GAP}(?:clean|safe)\b",
            r"\b(?:is|as) (?:clean|legitimate)\b",
            r"\bla (?:sach|hop le|an toan)\b",
            # "khach hang nay sach" (clean); "danh sach" (a list) is not a verdict
            r"\b(?:khach hang|tai khoan|giao dich)(?:\s+\S+){0,3}?\s+(?<!danh )sach\b",
            r"\bkhong (?:con )?dang ngo\b",
            r"\bwhitelist",
            r"\bdanh sach trang\b",
            r"\bdo not (?:raise|report)\b",
            r"\bkhong (?:can )?(?:bao cao|canh bao)\b",
            r"\bkhong can dieu tra\b",
            r"\bno further (?:action|investigation)\b",
            rf"\b(?:clos(?:e|ed|es|ing)|clear(?:ed|s|ing)?|dismiss(?:ed|es|ing)?){_GAP}"
            r"(?:cases?|alerts?)\b",
            r"\b(?:cases?|alerts?)\b(?:\s+\S+){0,2}?\s+(?:be|been)\s+(?:closed|cleared|dismissed)\b",
            r"\bdismiss",
            rf"\bdong{_GAP}(?:case|ho so|canh bao)\b",
            r"\bapprove",
            r"\bphe duyet\b",
            r"\badmin mode\b",
        )
    )
)

ROLES = ("src", "dst")
_ACCOUNT_WORD = r"(?:(?:cac tai khoan|tai khoan|tk|accounts?|the account)\s+)?"
_SRC_WORDS = ("tu", "from", "khoi")
_DST_WORDS = ("den", "toi", "sang", "cho", "vao", "ve", "to", "into")
_PREP_BEFORE = re.compile(
    rf"(?:^|[^a-z0-9])(?P<prep>{'|'.join(_SRC_WORDS + _DST_WORDS)})\s+{_ACCOUNT_WORD}$"
)
# "liên quan tới A01", "đề cập đến A01", "connected to A01": the preposition is not a direction
_NO_DIRECTION = re.compile(
    r"(?:^|[^a-z0-9])(?:lien quan|de cap|nhac|noi|related|linked|belongs?|thuoc|connected|tied"
    r"|refer(?:s|red|ring)?|mentioned)\s+$"
)
_SEGMENT_END = re.compile(r"[,;:.!?](?:\s|$)")
_VERB_WORDS = 4
# "nhận" folds to "nhan", and so do "cá nhân", "nhân viên": those are never the verb
_IN_VERBS = (
    r"(?<!ca )(?<!cong )nhan(?!\s+(?:vien|su|dan|khau|to|than|loai|chung|dang|thuc|cach))"
    r"|duoc chuyen|duoc nop|receives?|received|receiving|is credited|was credited"
)
_OUT_VERBS = (
    r"chuyen|gui|thanh toan|rut|sends?|sent|transfers?|transferred|pays?|paid|wires?|wired"
    r"|withdraws?|withdrew|debited"
)
_VERB = re.compile(rf"\b(?:(?P<dst>{_IN_VERBS})|(?P<src>{_OUT_VERBS}))\b")
# "có giao dịch chuyển khoản", "had 3 transfers": the verb word is a noun here
_NOUN_BEFORE_VERB = re.compile(
    r"(?:^|\s)(?:giao dich|lenh|cac|nhung|mot|so|had|has|have|made?|makes|\d+)\s+$"
)
# "chuyển về A01" is a destination; "thông tin về A01" is "about"
_OUT_VERB_BEFORE_VE = re.compile(rf"\b(?:{_OUT_VERBS})(?:\s+\S+){{0,2}}\s+$")
_CASH_DEPOSIT = re.compile(r"^(?:\s+\S+){0,2}?\s+tien mat\b")  # "gửi 390 triệu tiền mặt"
_HEDGES = re.compile(
    r"\b(?:co the la|co le|co kha nang (?:la|thuoc|do|bi)|duong nhu|hinh nhu|chac la|du doan"
    r"|may be|might be|could be|possibly|probably|perhaps|likely|presumably)\b"
)


def fold(text: str) -> str:
    """Lower case without diacritics: ``Đồng`` -> ``dong``."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _parts(literal: str) -> tuple[str, str | None, bool]:
    """(integer digits, fraction digits or None, grouped?) of a number as written.

    The last ``.`` / ``,`` starts a fraction when 1 or 2 digits follow it; every other separator
    (``.``, ``,``, space, no-break space) only groups thousands.
    """
    compact = literal.replace(" ", "").replace("\xa0", "")
    head, fraction = compact, None
    cut = max(compact.rfind("."), compact.rfind(","))
    if cut >= 0 and len(compact) - cut - 1 <= 2:
        head, fraction = compact[:cut], compact[cut + 1 :]
    grouped = len(head.replace(".", "").replace(",", "")) != len(head) or compact != literal
    return head.replace(".", "").replace(",", ""), fraction, grouped


def _numbers(text: str) -> Iterator[tuple[int, bool, tuple[int, int]]]:
    """(value, is_amount, span) of every number of ``text``.

    A money amount keeps its whole dong: the fraction of ``390,000,000.00 VND`` or of
    ``1.234.567,89 VND`` is dropped (VND has no subunit in use), so a wrong fraction is not
    caught. A fraction counts with a scale word (``1,5 ty`` = 1,500,000,000). A decimal without
    a scale, a currency word or thousands grouping (``score 100.0``) is no amount and no integer.
    """
    for m in _NUMBER.finditer(fold(text)):
        scale, currency = m.group("scale"), m.group("currency")
        digits, fraction, grouped = _parts(m.group("num"))
        if fraction is not None and scale is None and not (currency or grouped):
            continue
        if fraction is not None and scale is not None:
            value = Decimal(f"{digits}.{fraction}") * SCALES[scale]
            if value != value.to_integral_value():
                continue
            whole = int(value)
        else:
            whole = int(digits) * SCALES.get(scale or "", 1)
        yield whole, bool(scale or currency) or whole >= AMOUNT_FLOOR, m.span()


def extract_amounts(text: str) -> frozenset[int]:
    """Amounts of VND stated in a sentence: a number with a scale or a currency word, or a bare
    number of at least 1,000,000."""
    return frozenset(value for value, is_amount, _ in _numbers(text) if is_amount)


def extract_numbers(text: str) -> frozenset[int]:
    """Every integer of a string (separators removed), plus the amounts."""
    return frozenset(value for value, _, _ in _numbers(text))


def has_unreadable_amount(text: str) -> bool:
    """True when a money word follows a number that could not be read (``1.234.56 VND``).

    Something that looks like an amount and cannot be checked is flagged, never ignored.
    """
    spans = [span for _, is_amount, span in _numbers(text) if is_amount]
    for m in _MONEY_AFTER_DIGIT.finditer(fold(text)):
        word = m.start("word")
        if not any(start <= word < end for start, end in spans):
            return True
    return False


def extract_dates(text: str) -> frozenset[str]:
    """Dates as ``YYYY-MM-DD``; the calendar is not checked (a made-up date is simply not found)."""
    folded = fold(text)
    found = set()
    for pattern, order in _DATES:
        for m in pattern.finditer(folded):
            parts = dict(zip(order, (int(g) for g in m.groups()), strict=True))
            found.add(f"{parts['y']:04d}-{parts['m']:02d}-{parts['d']:02d}")
    return frozenset(found)


def _walk(value: Any) -> Iterator[Any]:
    """Every leaf of a nested dict / list value."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def _supporting_texts(evidence: Evidence) -> list[str]:
    texts = [evidence.text]
    if evidence.kind == "passage":
        texts += [u.text for u in evidence.untrusted if u.field == SUPPORTING_FIELD]
    return texts


def evidence_numbers(evidence: Evidence) -> frozenset[int]:
    """Integers an evidence item supports: from ``data``, ``text`` and a passage's chunk text."""
    found: set[int] = set()
    for leaf in _walk(evidence.data):
        if isinstance(leaf, bool):
            continue
        if isinstance(leaf, int):
            found.add(leaf)
        elif isinstance(leaf, float) and leaf.is_integer():
            found.add(int(leaf))
        elif isinstance(leaf, str):
            found |= extract_numbers(leaf)
    for text in _supporting_texts(evidence):
        found |= extract_numbers(text)
    return frozenset(found)


def evidence_dates(evidence: Evidence) -> frozenset[str]:
    """Dates an evidence item supports, from the same sources as `evidence_numbers`."""
    found: set[str] = set()
    for leaf in _walk(evidence.data):
        if isinstance(leaf, datetime | date):
            found.add(leaf.strftime("%Y-%m-%d"))
        elif isinstance(leaf, str):
            found |= extract_dates(leaf)
    for text in _supporting_texts(evidence):
        found |= extract_dates(text)
    return frozenset(found)


def is_verdict(text: str) -> bool:
    """True when a sentence clears, closes, approves or whitelists, or repeats an instruction to
    ignore the rules. A word list: it catches the planted phrases and close variants, not every
    way to say it. A status written by the system (``CLOSED``) does not match."""
    # "đồng" (the currency) folds to the same word as "đóng" (to close): take it out first
    currency_free = unicodedata.normalize("NFC", text).lower().replace("đồng", "vnd")
    return _VERDICTS.search(fold(currency_free)) is not None


def is_speculative(text: str) -> bool:
    """True when a sentence hedges ("có thể là", "might be", "possibly"). A word list: "có thể"
    before a verb (what someone can do) and the month of May are not hedges."""
    return _HEDGES.search(fold(text)) is not None


def _verb_role(after: str) -> str | None:
    """Role given by the earliest verb phrase starting in the first words of ``after``."""
    cut = _SEGMENT_END.search(after)
    words = (after[: cut.start()] if cut else after).split()
    head = " ".join(words[:_VERB_WORDS])
    window = " ".join(words[: _VERB_WORDS + 2])
    best: tuple[int, str] | None = None
    for m in _VERB.finditer(window):
        if m.start() >= len(head):
            break
        if m.group("src") and _NOUN_BEFORE_VERB.search(window[: m.start()]):
            continue  # "có giao dịch chuyển khoản": a noun, not what the account did
        role = "dst" if m.group("dst") else "src"
        if m.group("src") == "gui" and _CASH_DEPOSIT.match(window[m.end() :]):
            role = "dst"  # "gửi tiền mặt" is a cash deposit into the account
        if best is None or m.start() < best[0]:
            best = (m.start(), role)
    return best[1] if best else None


def account_roles(text: str, accounts: Collection[str]) -> dict[str, frozenset[str]]:
    """The side of a transfer (``src`` / ``dst``) a sentence gives to each account it names.

    A preposition right before the id decides first (``từ`` = src, ``đến`` = dst, but "liên quan
    tới" says nothing); without one, a verb in the 4 words after the id does ("nhận" = dst,
    "chuyển" = src). A pronoun is never traced back to an account. An account with no role is
    absent.
    """
    folded = fold(text)
    lowered = {a: a.lower() for a in accounts}
    mentions = sorted(
        (m.start(), m.end(), a)
        for a, low in lowered.items()
        for m in re.finditer(rf"(?<![a-z0-9]){re.escape(low)}(?![a-z0-9])", folded)
    )
    found: dict[str, set[str]] = {}
    for i, (start, end, account) in enumerate(mentions):
        prep = _PREP_BEFORE.search(folded[:start])
        word = prep.group("prep") if prep else None
        if word in _DST_WORDS and _NO_DIRECTION.search(folded[: prep.start("prep")]):
            word = None
        elif word == "ve" and not _OUT_VERB_BEFORE_VE.search(folded[: prep.start("prep")]):
            word = None  # "về" means "about" unless an outgoing verb precedes it
        if word:
            role = "src" if word in _SRC_WORDS else "dst"
        else:
            limit = mentions[i + 1][0] if i + 1 < len(mentions) else len(folded)
            role = _verb_role(folded[end:limit])
        if role:
            found.setdefault(account, set()).add(role)
    return {a: frozenset(r) for a, r in found.items()}
