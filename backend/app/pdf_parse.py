"""PDF parsing, document hierarchy and source grounding.

The parser retains page text and word boxes for exact source visualization, then
builds a lightweight clause hierarchy for section-aware retrieval/reasoning.
No OCR is attempted; scanned/image-only PDFs remain explicitly out of scope.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import fitz  # PyMuPDF

from .textutil import flatten, tok

_MAJOR_RE = re.compile(r"(?m)^\s*(\d{1,2})\.\s+([A-Z][A-Za-z0-9 ,/&'\-]{2,80})\s*$")
_MINOR_RE = re.compile(r"(?m)^\s*(\d{1,2}\.\d{1,2})\.?\s+(.+?)\s*$")


def parse_pdf(data: bytes) -> list[dict[str, Any]]:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        pages: list[dict[str, Any]] = []
        for i, page in enumerate(doc, start=1):
            raw = page.get_text("words")
            raw.sort(key=lambda w: (w[5], w[6], w[7]))
            words = [
                {"x0": float(w[0]), "y0": float(w[1]), "x1": float(w[2]), "y1": float(w[3]), "t": w[4]}
                for w in raw if w[4].strip()
            ]
            pages.append({
                "page": i,
                "width": float(page.rect.width),
                "height": float(page.rect.height),
                "text": page.get_text("text"),
                "words": words,
            })
        return pages
    finally:
        doc.close()


def full_text(pages: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in pages)


def _index(page: dict[str, Any]) -> tuple[str, list[int], list[int]]:
    parts: list[str] = []
    starts: list[int] = []
    word_idx: list[int] = []
    cursor = 0
    for wi, w in enumerate(page["words"]):
        t = tok(w["t"])
        if not t:
            continue
        parts.append(t)
        starts.append(cursor)
        word_idx.append(wi)
        cursor += len(t) + 1
    return " ".join(parts), starts, word_idx


def _rects(page: dict[str, Any], first: int, last: int) -> list[list[float]]:
    rows: dict[int, list[float]] = {}
    for w in page["words"][first:last + 1]:
        key = int(round(w["y0"]))
        hit = next((k for k in rows if abs(k - key) <= 2), key)
        if hit in rows:
            r = rows[hit]
            rows[hit] = [min(r[0], w["x0"]), min(r[1], w["y0"]), max(r[2], w["x1"]), max(r[3], w["y1"])]
        else:
            rows[hit] = [w["x0"], w["y0"], w["x1"], w["y1"]]
    return [rows[k] for k in sorted(rows)]


def ground_quote(pages: list[dict[str, Any]], quote: str, hint_page: int | None = None) -> dict[str, Any]:
    """Try exact word-level grounding first, then a cautious page fallback."""
    result = {"tier": 2, "page": hint_page, "rects": [], "section": "", "section_number": "", "excerpt": (quote or "").strip()}
    q = " ".join(tok(x) for x in (quote or "").split() if tok(x))
    if len(q) < 12:
        return result

    ordered = sorted(pages, key=lambda p: (p.get("page") != hint_page, p.get("page", 0)))
    probes = [q]
    if len(q) > 90:
        probes.append(q[:80].rsplit(" ", 1)[0])
    if len(q) > 45:
        probes.append(q[:40].rsplit(" ", 1)[0])

    for probe in probes:
        for page in ordered:
            joined, starts, word_idx = _index(page)
            at = joined.find(probe)
            if at < 0:
                continue
            first_tok = max(0, next((i for i, s in enumerate(starts) if s >= at), 0))
            end = at + len(probe)
            last_tok = max(first_tok, next((i - 1 for i, s in enumerate(starts) if s >= end), len(starts) - 1))
            first_w, last_w = word_idx[first_tok], word_idx[last_tok]
            sec_num, sec_title = section_for_position(page["text"], quote)
            return {
                "tier": 1,
                "page": page["page"],
                "rects": _rects(page, first_w, last_w),
                "section": f"Section {sec_num} {sec_title}".strip() if sec_num else "",
                "section_number": sec_num or "",
                "excerpt": (quote or "").strip(),
                "pageWidth": page["width"],
                "pageHeight": page["height"],
            }

    # Tier 2: only claim a page if distinctive terms overlap. Never manufacture coordinates.
    terms = [t for t in q.split() if len(t) > 5][:8]
    best, best_score = None, 0
    for page in pages:
        joined, _, _ = _index(page)
        score = sum(1 for t in terms if t in joined)
        if score > best_score:
            best, best_score = page, score
    if best is not None and best_score >= max(1, min(3, len(terms))):
        sec_num, sec_title = section_for_position(best["text"], quote)
        result.update({
            "page": best["page"],
            "section": f"Section {sec_num} {sec_title}".strip() if sec_num else "",
            "section_number": sec_num or "",
        })
    return result


def section_for_position(page_text: str, quote: str) -> tuple[str, str]:
    """Find the nearest actual numbered heading before the quote, positionally."""
    flat = flatten(page_text)
    qflat = flatten(quote)
    probe = qflat if len(qflat) <= 120 else qflat[:100]
    pos = flat.find(probe)
    if pos < 0 and len(qflat) > 24:
        pos = flat.find(qflat[:30])
    if pos < 0:
        return "", ""

    best: tuple[str, str, int] = ("", "", -1)
    heading_re = re.compile(r"(?m)^\s*(\d{1,2}(?:\.\d{1,2})?)\.?\s+([^\n.]{2,100})(?:\.|$)")
    for m in heading_re.finditer(page_text):
        start = len(flatten(page_text[:m.start()]))
        if start <= pos and start > best[2]:
            best = (m.group(1), m.group(2).strip(), start)
    return best[0], best[1]


@dataclass
class Clause:
    number: str
    title: str
    page: int
    start: int
    end: int
    text: str
    level: int
    parent: str = ""


@dataclass
class Document:
    pages: list[dict[str, Any]]
    clauses: list[Clause] = field(default_factory=list)

    @classmethod
    def from_pages(cls, pages: list[dict[str, Any]]) -> "Document":
        clauses: list[Clause] = []
        pat = re.compile(r"(?m)^\s*(\d{1,2}(?:\.\d{1,2})?)\.?\s+(.+?)\s*$")
        for p in pages:
            text = p["text"]
            matches = list(pat.finditer(text))
            for idx, m in enumerate(matches):
                num = m.group(1)
                raw = m.group(2).strip()
                level = 2 if "." in num else 1
                # Minor clauses use the first sentence as the clause title; major headings
                # normally contain no sentence terminator and remain intact.
                if level == 2 and "." in raw:
                    title, remainder = raw.split(".", 1)
                    title = title.strip()
                    body_inline = remainder.strip()
                else:
                    title = raw.rstrip(".")
                    body_inline = ""
                body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
                # Include any text after the heading line. For single-line minor clauses,
                # keep the remainder in the same clause rather than treating it as heading.
                after_line = text[m.end():body_end]
                body = flatten(" ".join(x for x in (body_inline, after_line) if x))
                combined = flatten(f"{num} {title}. {body}" if body else f"{num} {title}")
                parent = num.split(".", 1)[0] if level == 2 else ""
                clauses.append(Clause(num, title, p["page"], m.start(), body_end, combined, level, parent))
        clauses.sort(key=lambda c: (c.page, c.start))
        return cls(pages=pages, clauses=clauses)

    def clause(self, number: str | None) -> Clause | None:
        if not number:
            return None
        return next((c for c in self.clauses if c.number == number), None)

    def clause_text(self, clause: Clause | str | None) -> str:
        if isinstance(clause, str):
            clause = self.clause(clause)
        return clause.text if clause else ""

    def clause_body(self, clause: Clause | str | None) -> str:
        if isinstance(clause, str):
            clause = self.clause(clause)
        if not clause:
            return ""
        return clause.text.split(" ", 2)[2] if len(clause.text.split(" ", 2)) >= 3 else clause.text
