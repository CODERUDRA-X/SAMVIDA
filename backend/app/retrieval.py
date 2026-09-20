"""Hybrid clause/sentence retrieval without pretending to have embeddings.

Signals: lexical overlap, section/title overlap, exact phrase match, and
source proximity. This provides deterministic parent-child retrieval while
keeping the dependency footprint small for a solo hackathon build.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .pdf_parse import Clause, Document
from .textutil import flatten, tok

_STOP = {"the", "and", "or", "to", "of", "for", "in", "on", "a", "an", "is", "are", "this", "that", "what", "how"}


def _tokens(text: str) -> set[str]:
    return {tok(x) for x in re.findall(r"[A-Za-z0-9]+", text or "") if len(tok(x)) > 2 and tok(x) not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


@dataclass
class Chunk:
    id: str
    clause: str
    page: int
    title: str
    text: str
    sentence: str
    score: float = 0.0


class HybridRetriever:
    def __init__(self, doc: Document):
        self.doc = doc
        self.chunks: list[Chunk] = []
        for c in doc.clauses:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", flatten(c.text)) if s.strip()]
            if not sentences:
                sentences = [c.text]
            for i, s in enumerate(sentences):
                self.chunks.append(Chunk(f"{c.number}:{i}", c.number, c.page, c.title, c.text, s))

    def search(self, query: str, k: int = 8) -> list[Chunk]:
        q = flatten(query)
        qtok = _tokens(q)
        out: list[Chunk] = []
        for ch in self.chunks:
            body = _tokens(ch.sentence)
            title = _tokens(ch.title)
            score = 0.55 * _jaccard(qtok, body) + 0.25 * _jaccard(qtok, title)
            if q and q.lower() in ch.sentence.lower():
                score += 0.35
            m = re.search(r"(?:section|§)?\s*(\d{1,2}(?:\.\d{1,2})?)", q, re.I)
            if m and m.group(1) == ch.clause:
                score += 0.5
            ch.score = score
            out.append(ch)
        out.sort(key=lambda x: (-x.score, x.page, x.clause, x.id))
        return out[:k]

    def context(self, query: str, k: int = 8) -> str:
        rows = self.search(query, k)
        by_clause: dict[str, list[Chunk]] = {}
        for r in rows:
            by_clause.setdefault(r.clause, []).append(r)
        blocks = []
        for num, chunks in by_clause.items():
            first = chunks[0]
            blocks.append(f"[SECTION {num} — {first.title}]\n" + " ".join(c.sentence for c in sorted(chunks, key=lambda x: x.id)))
        return "\n\n".join(blocks)
