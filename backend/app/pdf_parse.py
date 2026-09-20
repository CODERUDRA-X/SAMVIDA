"""PDF parsing and source grounding.

Produces word-level bounding boxes so that a model-returned quote can be mapped
back to exact rectangles on the page (Tier 1 evidence). When that mapping fails,
callers fall back to section + page + excerpt (Tier 2).
"""
import re
from typing import Any

import fitz  # PyMuPDF

HEADING_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})?)[.)]?\s+([A-Z][A-Za-z ,/&'-]{2,60})\s*$")


def _tok(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_pdf(data: bytes) -> list[dict[str, Any]]:
    """Return one record per page: text, size, and positioned words."""
    doc = fitz.open(stream=data, filetype="pdf")
    pages: list[dict[str, Any]] = []
    for i, page in enumerate(doc, start=1):
        raw = page.get_text("words")  # x0, y0, x1, y1, word, block, line, word_no
        raw.sort(key=lambda w: (w[5], w[6], w[7]))
        words = [
            {"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "t": w[4]}
            for w in raw
            if w[4].strip()
        ]
        pages.append(
            {
                "page": i,
                "width": page.rect.width,
                "height": page.rect.height,
                "text": page.get_text("text"),
                "words": words,
            }
        )
    doc.close()
    return pages


def _index(page: dict[str, Any]) -> tuple[str, list[int], list[int]]:
    """Normalised token string for a page, with offset -> word-index maps."""
    joined_parts: list[str] = []
    starts: list[int] = []
    word_idx: list[int] = []
    cursor = 0
    for wi, w in enumerate(page["words"]):
        t = _tok(w["t"])
        if not t:
            continue
        joined_parts.append(t)
        starts.append(cursor)
        word_idx.append(wi)
        cursor += len(t) + 1
    return " ".join(joined_parts), starts, word_idx


def _rects(page: dict[str, Any], first: int, last: int) -> list[list[float]]:
    """Merge the bounding boxes of words[first..last] into per-line rectangles."""
    rows: dict[int, list[float]] = {}
    for w in page["words"][first : last + 1]:
        key = int(round(w["y0"]))
        # tolerate 2pt jitter within a line
        hit = next((k for k in rows if abs(k - key) <= 2), key)
        if hit in rows:
            r = rows[hit]
            rows[hit] = [min(r[0], w["x0"]), min(r[1], w["y0"]), max(r[2], w["x1"]), max(r[3], w["y1"])]
        else:
            rows[hit] = [w["x0"], w["y0"], w["x1"], w["y1"]]
    return [rows[k] for k in sorted(rows)]


def _section_for(page: dict[str, Any], anchor_word: str) -> str:
    """Nearest numbered heading at or above the quoted passage."""
    lines = page["text"].splitlines()
    anchor = _tok(anchor_word)
    last_heading = ""
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            last_heading = f"Section {m.group(1)} {m.group(2)}".strip()
        if anchor and anchor in _tok(line):
            return last_heading
    return last_heading


def ground_quote(pages: list[dict[str, Any]], quote: str, hint_page: int | None = None) -> dict[str, Any]:
    """Map a verbatim quote onto the document.

    Tier 1 -> exact word rectangles. Tier 2 -> section + page + excerpt.
    Never raises: an ungroundable quote still returns a usable Tier 2 record.
    """
    qt = " ".join(t for t in (_tok(x) for x in quote.split()) if t)
    result = {"tier": 2, "page": hint_page, "rects": [], "section": "", "excerpt": quote.strip()}
    if len(qt) < 12:
        return result

    order = sorted(pages, key=lambda p: (p["page"] != hint_page,))
    probes = [qt]
    if len(qt) > 90:
        probes.append(qt[:80].rsplit(" ", 1)[0])
    if len(qt) > 40:
        probes.append(qt[:36].rsplit(" ", 1)[0])

    for probe in probes:
        for page in order:
            joined, starts, word_idx = _index(page)
            at = joined.find(probe)
            if at == -1:
                continue
            # token span -> word span
            first_tok = next((i for i, s in enumerate(starts) if s >= at), 0)
            end = at + len(probe)
            last_tok = max(first_tok, next((i - 1 for i, s in enumerate(starts) if s >= end), len(starts) - 1))
            first_w, last_w = word_idx[first_tok], word_idx[last_tok]
            return {
                "tier": 1,
                "page": page["page"],
                "rects": _rects(page, first_w, last_w),
                "section": _section_for(page, page["words"][first_w]["t"]),
                "excerpt": quote.strip(),
                "pageWidth": page["width"],
                "pageHeight": page["height"],
            }

    # Tier 2: locate the most plausible page by distinctive word overlap
    terms = [t for t in qt.split() if len(t) > 5][:5]
    best, score = None, 0
    for page in pages:
        joined, _, _ = _index(page)
        hits = sum(1 for t in terms if t in joined)
        if hits > score:
            best, score = page, hits
    if best is not None and score:
        result["page"] = best["page"]
        result["section"] = _section_for(best, terms[0] if terms else "")
    return result


def full_text(pages: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in pages)
