"""Lightweight clause graph for explicit cross-clause relationships.

This is intentionally small and deterministic: it is GraphRAG-inspired, not a
claim that a hidden neural graph model is being used. Edges are created only
when the source text exposes a relationship clearly enough to support it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .pdf_parse import Clause, Document
from .textutil import flatten, words_to_digits

RELATIONS = {
    "OBLIGATION_OF",
    "REQUIRES_NOTICE",
    "HAS_DEADLINE",
    "CONDITIONAL_ON",
    "DEPENDS_ON",
    "TRIGGERS",
    "RENEWED_BY",
    "TERMINATED_BY",
    "SURVIVES_TERMINATION",
    "MODIFIES",
    "EXCEPTION_TO",
    "CONTRADICTS",
    "SUPERSEDES",
    "INDEMNIFIES",
}


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str
    evidence: str


class KnowledgeGraph:
    def __init__(self, nodes: Iterable[str], edges: Iterable[Edge]):
        self.nodes = list(dict.fromkeys(nodes))
        self.edges = list(edges)

    def edges_from(self, number: str, rel: str | None = None) -> list[Edge]:
        return [e for e in self.edges if e.src == f"clause:{number}" and (rel is None or e.rel == rel)]


def _node(number: str) -> str:
    return f"clause:{number}"


def _refs(text: str) -> list[str]:
    refs = re.findall(r"(?:Section|§)\s+(\d{1,2}(?:\.\d{1,2})?)", text, flags=re.I)
    return list(dict.fromkeys(refs))


def notice_days(text: str) -> int | None:
    t = words_to_digits(text)
    m = re.search(r"(\d{1,3})\s*\(?\d*\)?\s*days?\s+(?:prior|before|in advance)", t, re.I)
    return int(m.group(1)) if m else None


def _sent_with(doc: Document, clause: Clause | None, pattern: str) -> list[dict]:
    if not clause:
        return []
    raw = doc.clause_text(clause)
    rows: list[dict] = []
    for sent in re.split(r"(?<=[.!?])\s+", flatten(raw)):
        if re.search(pattern, sent, re.I):
            rows.append({"page": clause.page, "section_number": clause.number, "section": f"Section {clause.number} {clause.title}", "excerpt": sent})
    return rows


def build_knowledge_graph(doc: Document) -> KnowledgeGraph:
    nodes = [_node(c.number) for c in doc.clauses]
    edges: list[Edge] = []

    def add(src: str, rel: str, dst: str, evidence: str):
        if rel not in RELATIONS:
            return
        edge = Edge(_node(src), rel, _node(dst), flatten(evidence))
        if edge not in edges:
            edges.append(edge)

    for c in doc.clauses:
        text = doc.clause_text(c)
        norm = words_to_digits(text)
        refs = _refs(text)

        # Explicit deadline cues are self-edges because the deadline belongs to the clause.
        if re.search(r"\b(?:within|no later than|not less than|at least)\b", norm, re.I):
            add(c.number, "HAS_DEADLINE", c.number, re.search(r"[^.]*\b(?:within|no later than|not less than|at least)\b[^.]*", norm, re.I).group(0))
        # Explicit obligation party cues.
        if re.search(r"\b(?:shall|must|is responsible for|may terminate|may provide|may engage)\b", norm, re.I):
            add(c.number, "OBLIGATION_OF", c.number, text[:280])
        # Termination / survival semantics.
        if re.search(r"survive(?:s|d)? termination", norm, re.I):
            add(c.number, "SURVIVES_TERMINATION", c.number, re.search(r"[^.]*survive[^.]*termination[^.]*", norm, re.I).group(0))
        if re.search(r"terminate(?:d)?|termination|expiry|expiration", norm, re.I):
            for r in refs:
                if r != c.number and re.search(rf"Section\s+{re.escape(r)}", text, re.I):
                    add(c.number, "TERMINATED_BY", r, f"{c.number} explicitly references Section {r} in termination context")
        # Referenced notices and formal notice channels.
        if re.search(r"notice|notices|written", norm, re.I):
            for r in refs:
                if r != c.number:
                    add(c.number, "REQUIRES_NOTICE", r, f"{c.number} references Section {r} while defining notice mechanics")
        # Conditions built from explicit 'provided that', 'unless', 'only if'.
        if re.search(r"\bprovided that\b|\bunless\b|\bonly if\b|\bexcept\b", norm, re.I):
            for r in refs:
                add(c.number, "CONDITIONAL_ON", r, text[:300])
        # Contract text commonly exposes dependencies via 'in Section X' / 'according to Section X'.
        for r in refs:
            if re.search(rf"\b(?:in|under|pursuant to|according to|as set out in)\s+(?:Section|§)\s+{re.escape(r)}", norm, re.I):
                add(c.number, "DEPENDS_ON", r, f"{c.number} depends on mechanics in Section {r}")
        # Renewal: connect initial term to automatic renewal, and renewal economics to renewal clause.
        if re.search(r"automatically\s+renew|renew\s+perpetually|successive\s+periods", norm, re.I):
            for sibling in doc.clauses:
                if sibling.parent == c.parent and sibling.number != c.number and re.search(r"notice|initial term|term", doc.clause_text(sibling), re.I):
                    if sibling.number.startswith(c.parent + "."):
                        add(sibling.number, "RENEWED_BY", c.number, f"{sibling.number} and {c.number} define the term-to-renewal path")
        if re.search(r"increase the subscription fees|price adjustment|increase.*fees", norm, re.I):
            renewal = next((x for x in doc.clauses if re.search(r"automatically\s+renew|renew\s+perpetually", doc.clause_text(x), re.I)), None)
            if renewal:
                add(c.number, "CONDITIONAL_ON", renewal.number, "Price adjustment is effective on a renewal term")
        # Explicit survival / post-termination references.
        if re.search(r"accrued.*effective date|remain payable|does not relieve", norm, re.I):
            term = next((x for x in doc.clauses if x.number.startswith("9.") and re.search(r"terminate", doc.clause_text(x), re.I)), None)
            if term and term.number != c.number:
                add(term.number, "TRIGGERS", c.number, f"{term.number} establishes an exit event tied to {c.number}'s accrued-fee consequence")
        if re.search(r"indemnif", norm, re.I):
            for r in refs:
                if r != c.number:
                    add(c.number, "INDEMNIFIES", r, f"{c.number} ties indemnification to Section {r}")
        if re.search(r"supersede", norm, re.I):
            add(c.number, "SUPERSEDES", c.number, re.search(r"[^.]*supersede[^.]*", norm, re.I).group(0))
        if re.search(r"modify|amend", norm, re.I) and refs:
            for r in refs:
                add(c.number, "MODIFIES", r, f"{c.number} governs modification while referencing Section {r}")

    return KnowledgeGraph(nodes, edges)
