"""Deterministic text/date helpers shared by parsing, retrieval and verification."""
from __future__ import annotations

import re
from datetime import date, timedelta

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1
)}
_MONTH_RE = "|".join(_MONTHS)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?[,]?\s+(\d{{4}})\b", re.I)
_MDY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(\d{{4}})\b", re.I)
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\b(?!\.?[,]?\s+\d{{4}})", re.I)
MONEY_RE = re.compile(r"\bUSD\s?[\d,]+(?:\.\d+)?\b", re.I)
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%\b")

_ABBREV = {"inc", "ltd", "no", "co", "corp", "sec", "e.g", "i.e", "vs", "pvt", "llc", "art", "u.s"}
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def flatten(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def tok(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def tokens(s: str) -> list[str]:
    return [x for x in (tok(p) for p in re.split(r"\s+", s or "")) if x]


def words_to_digits(s: str) -> str:
    """Normalize the small number vocabulary commonly found in contracts."""
    pattern = r"\b(?:" + "|".join(NUMBER_WORDS.keys()) + r")(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?\b"

    def sub(m: re.Match[str]) -> str:
        parts = re.split(r"[-\s]", m.group(0).lower())
        return str(sum(NUMBER_WORDS.get(p, 0) for p in parts))

    return re.sub(pattern, sub, s or "", flags=re.I)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Return sentence offsets without splitting common legal abbreviations."""
    text = text or ""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in re.finditer(r"[.!?]\s+(?=[A-Z“\"(])", text):
        tail = re.findall(r"([A-Za-z.]+)$", text[start:m.start()])
        if tail and tail[-1].lower().strip(".") in _ABBREV:
            continue
        spans.append((start, m.start() + 1))
        start = m.end()
    if text[start:].strip():
        spans.append((start, len(text.rstrip())))
    return spans


def sentences(text: str) -> list[str]:
    return [text[a:b] for a, b in sentence_spans(text)]


def parse_date(text: str) -> date | None:
    for rx, order in ((_ISO, "ymd"), (_DMY, "dmy"), (_MDY, "mdy")):
        m = rx.search(text or "")
        if not m:
            continue
        try:
            if order == "ymd":
                return date(int(m[1]), int(m[2]), int(m[3]))
            if order == "dmy":
                return date(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
            return date(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))
        except (ValueError, KeyError):
            continue
    return None


def parse_day_month(text: str) -> tuple[int, int] | None:
    m = _DAY_MONTH.search(text or "")
    if not m:
        return None
    return _MONTHS[m[2].lower()], int(m[1])


def minus_days(d: date, n: int) -> date:
    return d - timedelta(days=n)


def fmt_date(d: date | str | None) -> str:
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d)
        except ValueError:
            return d
    return f"{d.day} {d.strftime('%b %Y')}" if d else ""
