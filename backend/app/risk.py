"""Deterministic risk engine.

The language model extracts and quotes. These rules — and only these rules —
decide whether the agent halts. That keeps the answer to "why did the agent
stop?" explicit, inspectable and reproducible across demo runs.
"""
import re
from typing import Any

HIGH = "high"
MEDIUM = "medium"
LOW = "low"


def _days_before(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*\)?\s*days?\s+(?:prior|before|in advance)", text)
    return int(m.group(1)) if m else None


def _payment_days(text: str) -> int | None:
    m = re.search(r"payable\s+within\s+(?:[a-z\- ]*?)\(?(\d{1,3})\)?\s*days?", text)
    if not m:
        m = re.search(r"\(?(\d{1,3})\)?\s*days?\s+of\s+the\s+invoice", text)
    return int(m.group(1)) if m else None


def _rule_auto_renewal(t: str) -> bool:
    return bool(re.search(r"automatic(?:ally)?\s+renew|auto-?renew|successive\s+(?:periods|terms)|renew\s+perpetually|perpetual", t))


def _rule_exit_fee(t: str) -> bool:
    return bool(re.search(r"early\s+termination\s+fee|termination\s+fee|exit\s+fee", t))


def _rule_price_escalation(t: str) -> bool:
    return bool(re.search(r"increase\s+the\s+(?:subscription\s+)?fees|price\s+adjustment|fee\s+escalation", t))


RULES: list[dict[str, Any]] = [
    {
        "id": "R1-AUTO-RENEWAL",
        "label": "Automatic or perpetual renewal",
        "severity": HIGH,
        "match": lambda t: _rule_auto_renewal(t),
        "why": "The agreement renews without a further signature. If the notice window is missed, another full term is committed automatically.",
    },
    {
        "id": "R2-PAYMENT-TERM",
        "label": "Payment term longer than 60 days",
        "severity": HIGH,
        "match": lambda t: (_payment_days(t) or 0) > 60,
        "why": "The payment window is materially longer than a standard Net-30 or Net-45 term and affects working-capital planning.",
    },
    {
        "id": "R3-EXIT-FEE",
        "label": "Early termination fee",
        "severity": HIGH,
        "match": lambda t: _rule_exit_fee(t),
        "why": "Leaving the agreement before the end of a term carries a fixed charge in addition to accrued fees.",
    },
    {
        "id": "R4-NOTICE-WINDOW",
        "label": "Notice period of 60 days or more",
        "severity": MEDIUM,
        "match": lambda t: (_days_before(t) or 0) >= 60,
        "why": "The notice window opens well before the term ends, so the action date is much earlier than the renewal date.",
    },
    {
        "id": "R5-PRICE-ESCALATION",
        "label": "Contractual price escalation right",
        "severity": MEDIUM,
        "match": lambda t: _rule_price_escalation(t),
        "why": "Fees can be increased at renewal within a contractual ceiling, so the renewal cost is not the current cost.",
    },
]

_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}


def assess(finding: dict[str, Any]) -> dict[str, Any]:
    """Attach risk, the rules that fired, and a human-readable reason."""
    hay = " ".join(
        str(finding.get(k, "")) for k in ("quote", "summary", "label", "category")
    ).lower()
    hay = re.sub(r"\s+", " ", hay)

    fired = []
    for rule in RULES:
        try:
            if rule["match"](hay):
                fired.append(rule)
        except Exception:  # a malformed quote must never break the pipeline
            continue

    if not fired:
        finding["risk"] = LOW
        finding["rules"] = []
        finding["why"] = ""
        return finding

    fired.sort(key=lambda r: _ORDER[r["severity"]], reverse=True)
    top = fired[0]
    finding["risk"] = top["severity"]
    finding["rules"] = [{"id": r["id"], "label": r["label"]} for r in fired]
    finding["why"] = top["why"]
    finding["ruleId"] = top["id"]
    return finding


def requires_intervention(finding: dict[str, Any]) -> bool:
    return finding.get("risk") == HIGH and not finding.get("decision")
