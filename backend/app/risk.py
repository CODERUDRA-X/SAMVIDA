"""Deterministic review policy.

The model extracts source-backed facts. These explicit product rules determine
when controlled execution must stop; they are not universal legal standards.
"""
from __future__ import annotations

import re
from typing import Any

from .textutil import words_to_digits

HIGH, MEDIUM, LOW = "high", "medium", "low"


def _days_before(text: str) -> int | None:
    text = words_to_digits(text)
    m = re.search(r"(\d{1,3})\s*(?:\([^)]+\))?\s*days?\s+(?:prior|before|in advance)", text, re.I)
    return int(m.group(1)) if m else None


def _payment_days(text: str) -> int | None:
    text = words_to_digits(text)
    m = re.search(r"payable\s+within\s+(?:[a-z\-]+\s+)?\(?([0-9]{1,3})\)?\s*(?:\([0-9]{1,3}\))?\s*days?", text, re.I)
    if not m:
        m = re.search(r"(\d{1,3})\s*days?\s+of\s+the\s+invoice", text, re.I)
    return int(m.group(1)) if m else None


def _auto(t: str) -> bool:
    return bool(re.search(r"automatic(?:ally)?\s+renew|auto-?renew|successive\s+(?:periods|terms)|renew\s+perpetually|perpetual", t, re.I))


def _exit_fee(t: str) -> bool:
    return bool(re.search(r"early\s+termination\s+fee|termination\s+fee|exit\s+fee", t, re.I))


def _price(t: str) -> bool:
    return bool(re.search(r"increase\s+(?:the\s+)?(?:subscription\s+)?fees|price\s+adjustment|fee\s+escalation", t, re.I))


RULES: list[dict[str, Any]] = [
    {"id": "R1-AUTO-RENEWAL", "shortId": "R1", "label": "Automatic or perpetual renewal", "severity": HIGH, "match": _auto,
     "why": "Product policy requires human verification before proceeding when the agreement renews automatically or perpetually."},
    {"id": "R2-PAYMENT-TERM", "shortId": "R2", "label": "Payment window over 60 days", "severity": HIGH, "match": lambda t: (_payment_days(t) or 0) > 60,
     "why": "Product policy treats a payment window over 60 days as a high-review condition because it affects cash-flow planning."},
    {"id": "R3-EXIT-FEE", "shortId": "R3", "label": "Early termination fee", "severity": HIGH, "match": _exit_fee,
     "why": "The clause contains a separate termination charge; the agent pauses so the user can verify the finding before action planning."},
    {"id": "R4-NOTICE-WINDOW", "shortId": "R4", "label": "Notice period of 60 days or more", "severity": MEDIUM, "match": lambda t: (_days_before(t) or 0) >= 60,
     "why": "The contract creates a notice window of at least 60 days before the relevant event."},
    {"id": "R5-PRICE-ESCALATION", "shortId": "R5", "label": "Contractual price escalation right", "severity": MEDIUM, "match": _price,
     "why": "The contract gives the Supplier a right to increase fees subject to the stated notice and cap."},
]
_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}


def assess(finding: dict[str, Any]) -> dict[str, Any]:
    hay = " ".join(str(finding.get(k, "")) for k in ("quote", "summary", "label", "category")).lower()
    fired = []
    for rule in RULES:
        try:
            if rule["match"](hay):
                fired.append(rule)
        except Exception:
            continue
    if not fired:
        finding.update({"risk": LOW, "rules": [], "why": ""})
        return finding
    fired.sort(key=lambda r: _ORDER[r["severity"]], reverse=True)
    top = fired[0]
    finding.update({
        "risk": top["severity"],
        "ruleId": top["id"],
        "rules": [{"id": r["id"], "shortId": r["shortId"], "label": r["label"], "severity": r["severity"]} for r in fired],
        "why": " ".join(r["why"] for r in fired[:2]),
    })
    return finding


def pending_priority(finding: dict[str, Any]) -> tuple[int, int]:
    priority = {"R1-AUTO-RENEWAL": 0, "R3-EXIT-FEE": 1, "R2-PAYMENT-TERM": 2}
    return (priority.get(finding.get("ruleId"), 9), int(finding.get("page") or 999))


def requires_intervention(finding: dict[str, Any]) -> bool:
    return finding.get("risk") == HIGH and not finding.get("decision")
