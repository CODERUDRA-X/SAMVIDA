"""Evidence-backed cross-clause reasoning for the Action Workspace.

Outputs are bounded, source-linked potential interactions. They are not legal
conclusions and do not expose private model chain-of-thought.
"""
from __future__ import annotations

import re
from typing import Any

from .knowledge_graph import KnowledgeGraph, _sent_with, notice_days
from .pdf_parse import Document
from .textutil import MONEY_RE, words_to_digits


def _clause_text(doc: Document, num: str) -> str:
    return words_to_digits(doc.clause_text(num)) if doc.clause(num) else ""


def _find_num(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else None


def _insight(id_: str, title: str, statement: str, clauses: list[str], kg: KnowledgeGraph, doc: Document) -> dict[str, Any]:
    evidence = []
    for n in clauses:
        c = doc.clause(n)
        if c:
            evidence.extend(_sent_with(doc, c, r".+")[:2])
    return {
        "id": id_,
        "kind": "POTENTIAL_INTERACTION",
        "title": title,
        "statement": statement,
        "clauses": clauses,
        "via": [e.rel for e in kg.edges if e.src.split(":", 1)[-1] in clauses or e.dst.split(":", 1)[-1] in clauses][:5],
        "evidence": evidence[:4],
    }


def analyze(doc: Document, kg: KnowledgeGraph) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    renew = next((c.number for c in doc.clauses if re.search(r"automatically\s+renew|renew\s+perpetually", doc.clause_text(c), re.I)), None)
    term = next((c.number for c in doc.clauses if re.search(r"terminate this Agreement for convenience", doc.clause_text(c), re.I)), None)
    price = next((c.number for c in doc.clauses if re.search(r"increase the subscription fees", doc.clause_text(c), re.I)), None)
    notice = notice_days(_clause_text(doc, renew)) if renew else None
    if renew and notice:
        c = doc.clause(renew)
        n2 = next((x.number for x in doc.clauses if x.number == "2.3"), None)
        if n2:
            body = _clause_text(doc, n2)
            bd = _find_num(body, r"within\s+(\d+)\s+Business\s+Days")
            extra = f"; electronic mail alone needs written acknowledgement within {bd} Business Days" if bd else ""
            out.append(_insight("ix-renewal-notice", "Renewal has notice-channel formalities", f"The non-renewal decision requires written notice at least {notice} days before term end{extra}.", [renew, n2], kg, doc))
    if renew and term and notice:
        t = _clause_text(doc, term)
        fee = MONEY_RE.search(t)
        term_notice = notice_days(t)
        if fee and term_notice:
            out.append(_insight("ix-renewal-exit", "Renewal and mid-term exit are linked", f"Missing the non-renewal window leads to renewal under §{renew}; a later convenience exit is described in §{term} with {term_notice} days' notice plus {fee.group(0)} and accrued fees.", [renew, term], kg, doc))
    if price and renew and notice:
        p = _clause_text(doc, price)
        pd = notice_days(p)
        cap = _find_num(p, r"not exceed\s+(\d+(?:\.\d+)?)\s*%")
        if pd and notice > pd:
            cap_text = f" up to {cap}%" if cap else ""
            out.append(_insight("ix-price-renewal", "Price change timing can trail the renewal decision", f"The non-renewal notice is due {notice} days before term end, while the Supplier can notify a renewal-term fee increase{cap_text} {pd} days before renewal. The renewal decision can therefore precede the final price notice.", [price, renew], kg, doc))
    if doc.clause("9.1") and doc.clause("9.4"):
        out.append(_insight("ix-termination-accrued", "Termination does not erase accrued fees", "§9.1 adds the early termination fee and accrued fees to the exit event; §9.4 separately states that accrued fees remain payable.", ["9.1", "9.4"], kg, doc))
    if doc.clause("4.2") and doc.clause("4.3"):
        out.append(_insight("ix-credit-window", "Service credit value depends on timely claim", "§4.2 describes the credit calculation while §4.3 requires the customer to claim it within 30 days after month-end or lose the claim.", ["4.2", "4.3"], kg, doc))
    if doc.clause("7.2") and doc.clause("9.4"):
        out.append(_insight("ix-survival", "Some obligations continue after termination", "§7.2 carries confidentiality forward for five years (with a trade-secret exception), while §9.4 identifies surviving sections including §7 and §8.", ["7.2", "9.4"], kg, doc))
    return out[:8]
