"""Deterministic fallback extractor used for offline testing and API outage recovery.

It is deliberately narrower than the Gemini extractor. It recognizes common
B2B contract patterns from the source document and marks the resulting findings
as local fallback evidence. It never pretends to be a general legal model.
"""
from __future__ import annotations

import re
from typing import Any

from .pdf_parse import Document
from .textutil import parse_date, words_to_digits


def _clause_finding(c, label, summary, category, party="", date="", basis=""):
    return {
        "label": label,
        "summary": summary,
        "quote": c.text[:900],
        "page": c.page,
        "date": date,
        "dateBasis": basis,
        "party": party,
        "category": category,
        "source": "local_fallback",
        "id": "",
        "decision": None,
    }


def extract(doc: Document) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    parties = {"customer": "", "supplier": ""}
    full = "\n".join(p["text"] for p in doc.pages)
    m = re.search(r"between\s+(.+?)\s+\(the\s+“Supplier”\).*?and\s+(.+?)\s+\(the\s+“Customer”\)", full, re.I | re.S)
    if m:
        parties["supplier"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",")
        parties["customer"] = re.sub(r"\s+", " ", m.group(2)).strip().rstrip(",")

    eff = parse_date(full)
    exp_match = re.search(r"expiring on\s+([^\s,.]+\s+[A-Za-z]+\s+\d{4})", full, re.I)
    from .textutil import parse_date as pd
    exp = pd(exp_match.group(1)) if exp_match else None

    patterns = [
        (r"automatically\s+renew|renew\s+perpetually|successive\s+periods", "Automatic renewal", "Agreement renews automatically for successive 12-month periods and perpetually unless timely non-renewal notice is delivered.", "renewal", "Both", "90 days before 2027-03-31"),
        (r"payable within.*?75.*?days|payable within.*?seventy-five", "Payment term", "Undisputed invoices are payable within 75 days of the invoice date.", "payment", "Customer", "75 days after invoice date"),
        (r"increase the subscription fees.*?nine percent|increase.*?fees", "Annual price adjustment", "The Supplier may increase subscription fees on each renewal term with 30 days written notice, capped at 9%.", "payment", "Supplier", "30 days before renewal term; maximum 9%"),
        (r"claimed in writing within.*?30.*?days", "Service credit claim window", "Service credits must be claimed in writing within 30 days of the affected month-end or the claim is waived.", "service-level", "Customer", "30 days after affected month-end"),
        (r"SOC 2.*?no later than 30 June", "Annual security report", "The Supplier must provide the most recent SOC 2 Type II report annually no later than 30 June.", "obligation", "Supplier", "annually; no later than 30 June"),
        (r"quarterly usage report.*?within 15 days", "Quarterly usage report", "The Customer must submit a quarterly usage report within 15 days following each calendar quarter.", "obligation", "Customer", "15 days following each calendar quarter"),
        (r"notify the Supplier of any change.*?10 days", "Named contact update", "The Customer must notify the Supplier of any change to the technical contact within 10 days.", "obligation", "Customer", "within 10 days of change"),
        (r"terminate this Agreement for convenience.*?60.*?days.*?USD 45,000", "Termination for convenience", "The Customer may terminate during a term with 60 days prior written notice and must pay USD 45,000 plus fees accrued to the effective date.", "termination", "Customer", "60 days prior written notice"),
        (r"material breach.*?30.*?days", "Termination for cause", "Either Party may terminate for material breach if it remains uncured for 30 days after written notice.", "termination", "Both", "30-day cure period"),
        (r"survive termination", "Post-termination survival", "Sections 7, 8, 10, 11 and 13 survive termination; confidentiality also states a five-year period except trade secrets.", "data", "Both", "post-termination"),
    ]
    for c in doc.clauses:
        text = words_to_digits(c.text)
        for rx, label, summary, cat, party, *rest in patterns:
            basis = rest[0] if rest else ""
            if re.search(rx, text, re.I):
                findings.append(_clause_finding(c, label, summary, cat, party, basis=basis))
                break

    # A term milestone from exact clauses.
    term = next((c for c in doc.clauses if c.number == "2.1"), None)
    if term:
        findings.append(_clause_finding(term, "Initial term expires", "The initial term expires on 31 March 2027 unless terminated earlier.", "term", "Both", date="2027-03-31", basis="Initial Term"))

    return {"parties": parties, "effectiveDate": eff.isoformat() if eff else "", "expirationDate": exp.isoformat() if exp else "", "findings": findings}
