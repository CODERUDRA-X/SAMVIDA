"""Deterministic chain-of-verification for extracted claims.

This records observable checks (quote grounding, numeric/date consistency,
party presence) rather than exposing private model reasoning. A finding gets
one of four review statuses.
"""
from __future__ import annotations

import re
from typing import Any

from .pdf_parse import Document, ground_quote
from .textutil import parse_date, words_to_digits

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


def _claim_numbers(text: str) -> set[str]:
    t = words_to_digits(text or "")
    return {m.group(0).replace(",", "") for m in re.finditer(r"\b\d+(?:\.\d+)?\b", t)}


def _claim_money(text: str) -> set[str]:
    return {m.group(0).replace(" ", "").lower() for m in re.finditer(r"\bUSD\s?[\d,]+(?:\.\d+)?\b", text or "", re.I)}


def verify_finding(finding: dict[str, Any], doc: Document, evidence: dict[str, Any]) -> dict[str, Any]:
    quote = (finding.get("quote") or "").strip()
    summary = (finding.get("summary") or "").strip()
    checks: list[dict[str, Any]] = []

    exact = evidence.get("tier") == 1
    checks.append({"question": "Is the quoted passage locatable in the source?", "status": SUPPORTED if exact else PARTIALLY_SUPPORTED if evidence.get("page") else INSUFFICIENT_EVIDENCE, "evidence": evidence.get("excerpt", quote)})

    qnums = _claim_numbers(quote)
    snums = _claim_numbers(summary)
    if snums:
        missing = sorted(nums for nums in snums if nums not in qnums)
        checks.append({"question": "Do numeric claims in the summary appear in the quoted source?", "status": SUPPORTED if not missing else CONFLICTING_EVIDENCE, "evidence": "Numbers checked: " + ", ".join(sorted(snums))})

    money = _claim_money(summary)
    if money:
        qmoney = _claim_money(quote)
        checks.append({"question": "Do monetary claims in the summary appear in the quote?", "status": SUPPORTED if money <= qmoney else CONFLICTING_EVIDENCE, "evidence": "Monetary atoms checked against quote."})

    fdate = (finding.get("date") or "").strip()
    if fdate:
        dt = parse_date(quote)
        checks.append({"question": "Is the stated absolute date supported by the quote?", "status": SUPPORTED if dt and dt.isoformat() == fdate else PARTIALLY_SUPPORTED if dt else INSUFFICIENT_EVIDENCE, "evidence": dt.isoformat() if dt else "No absolute date found in quote."})

    party = (finding.get("party") or "").strip()
    if party and party not in {"Both", "Customer", "Supplier"}:
        checks.append({"question": "Is the party value valid?", "status": INSUFFICIENT_EVIDENCE, "evidence": party})

    statuses = [c["status"] for c in checks]
    if CONFLICTING_EVIDENCE in statuses:
        overall = CONFLICTING_EVIDENCE
    elif INSUFFICIENT_EVIDENCE in statuses and not exact:
        overall = INSUFFICIENT_EVIDENCE
    elif PARTIALLY_SUPPORTED in statuses:
        overall = PARTIALLY_SUPPORTED
    else:
        overall = SUPPORTED

    result = dict(finding)
    result["verification_status"] = overall
    result["verification_checks"] = checks
    result["verification_confidence"] = {SUPPORTED: "high", PARTIALLY_SUPPORTED: "medium", INSUFFICIENT_EVIDENCE: "low", CONFLICTING_EVIDENCE: "low"}[overall]
    return result
