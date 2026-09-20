"""Build an action-oriented, source-linked timeline from extracted findings."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import config
from .textutil import fmt_date, parse_date, parse_day_month, words_to_digits

ACTION = "ACTION"
MILESTONE = "MILESTONE"
CONDITION = "CONDITION"
RELATIVE_DEADLINE = "RELATIVE_DEADLINE"
ALERT = "ALERT"

OVERDUE = "OVERDUE"
DUE_SOON = "DUE_SOON"
UPCOMING = "UPCOMING"
TRACKED = "TRACKED"
RELATIVE = "RELATIVE"

CONFIRMED = "CONFIRMED"
PENDING = "PENDING"
ROUTED = "ROUTED FOR REVIEW"

_FEE_RE = re.compile(r"\bUSD\s?[\d,]+(?:\.\d+)?\b", re.I)


def _today() -> date:
    return config.today()


def _date_status(d: date | None) -> str:
    if d is None:
        return TRACKED
    delta = (d - _today()).days
    if delta < 0:
        return OVERDUE
    if delta <= 30:
        return DUE_SOON
    return UPCOMING


def _iso(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "").strip())
    except (TypeError, ValueError):
        return None


def _infer_date(f: dict[str, Any], effective_date: str = "", expiration_date: str = "") -> tuple[str, str]:
    explicit = _iso(f.get("date", ""))
    basis = str(f.get("dateBasis", "") or "").strip()
    if explicit:
        return explicit.isoformat(), basis

    t = words_to_digits(basis)
    exp = _iso(expiration_date)
    m = re.search(r"(\d{1,3})\s+days?\s+before\s+(\d{4}-\d{2}-\d{2})", t, re.I)
    if m:
        from datetime import timedelta
        return (date.fromisoformat(m.group(2)) - timedelta(days=int(m.group(1)))).isoformat(), basis
    if re.search(r"annual|each calendar year", t, re.I):
        dm = parse_day_month(t)
        if dm:
            month, day = dm
            try:
                d = date(_today().year, month, day)
                eff = _iso(effective_date)
                if eff and d < eff:
                    d = date(_today().year + 1, month, day)
                return d.isoformat(), basis
            except ValueError:
                pass
    if exp and re.search(r"before.*(?:term ends|term expiry|term expiration)", t, re.I):
        m = re.search(r"(\d{1,3})\s+days?", t, re.I)
        if m:
            from datetime import timedelta
            return (exp - timedelta(days=int(m.group(1)))).isoformat(), basis
    return "", basis


def _fee(*texts: str) -> str:
    for text in texts:
        m = _FEE_RE.search(text or "")
        if m:
            return m.group(0)
    return ""


def _norm_quote(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").lower()).strip()


def _major(section: str) -> str:
    m = re.search(r"Section\s+(\d+)", section or "", re.I)
    return m.group(1) if m else ""


def dedup_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Merge only clearly overlapping extraction results, preferring evidence-rich records."""
    order = {"high": 2, "medium": 1, "low": 0}
    used = [False] * len(findings)
    groups: list[list[dict[str, Any]]] = []
    for i, f in enumerate(findings):
        if used[i]:
            continue
        used[i] = True
        q1 = _norm_quote(f.get("quote", ""))
        sec1 = (f.get("evidence") or {}).get("section", "")
        cat1 = f.get("category", "")
        group = [f]
        for j in range(i + 1, len(findings)):
            if used[j]:
                continue
            g = findings[j]
            q2 = _norm_quote(g.get("quote", ""))
            sec2 = (g.get("evidence") or {}).get("section", "")
            cat2 = g.get("category", "")
            same_clause = bool(sec1 and sec2 and sec1 == sec2)
            renewal_family = cat1 == cat2 == "renewal" or {cat1, cat2} <= {"renewal", "obligation"} and _major(sec1) == "2" and _major(sec2) == "2"
            overlaps = len(q1) >= 40 and len(q2) >= 40 and (q1 in q2 or q2 in q1)
            if overlaps and (same_clause or renewal_family):
                used[j] = True
                group.append(g)
        groups.append(group)

    merged: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        canon = dict(sorted(group, key=lambda f: (order.get(f.get("risk", "low"), 0), int((f.get("evidence") or {}).get("tier") == 1), len(f.get("quote", ""))), reverse=True)[0])
        canon["mergedFrom"] = [x["id"] for x in group if x.get("id") != canon.get("id")]
        canon["mergedLabels"] = [x["label"] for x in group if x.get("label") != canon.get("label")]
        merged.append(canon)
    return merged, len(findings) - len(merged)


def _classify(f: dict[str, Any], effective_date: str = "", expiration_date: str = "") -> dict[str, Any] | None:
    cat = f.get("category", "")
    hay = f"{f.get('label', '')} {f.get('summary', '')} {f.get('quote', '')}".lower()
    d, basis = _infer_date(f, effective_date, expiration_date)
    parsed = _iso(d)
    label = f.get("label", "Finding")
    meaning = f.get("summary", "")
    consequence = ""

    if cat == "term":
        kind, temporal = MILESTONE, _date_status(parsed) if parsed else TRACKED
    elif cat == "renewal":
        kind, temporal = ACTION, _date_status(parsed) if parsed else TRACKED
        if not basis:
            basis = "Non-renewal notice window"
        consequence = "Missing the notice window permits the agreement to renew for another term."
    elif cat == "payment" and any(x in hay for x in ("adjustment", "increase", "escalat")):
        kind, temporal = CONDITION, TRACKED
        consequence = "The renewal-term fee may change within the contract's stated notice and cap."
    elif cat == "payment":
        kind, temporal = (ACTION, _date_status(parsed)) if parsed else (RELATIVE_DEADLINE, RELATIVE)
    elif cat == "termination":
        kind = CONDITION if any(w in hay for w in ("cause", "breach", "insolven")) else ACTION
        temporal = _date_status(parsed) if parsed else TRACKED
        if "accrued" in hay:
            consequence = "Accrued fees remain payable in addition to any stated termination fee."
    elif cat == "service-level":
        kind, temporal = (ACTION, _date_status(parsed)) if parsed else (RELATIVE_DEADLINE, RELATIVE)
    elif cat in {"obligation", "data"}:
        if "survive termination" in hay or "post-termination survival" in hay:
            kind, temporal = CONDITION, TRACKED
        else:
            kind, temporal = (ACTION, _date_status(parsed)) if parsed else (ACTION, TRACKED)
        if parsed and _date_status(parsed) == OVERDUE:
            kind = ALERT
    else:
        return None

    decision = f.get("decision") or ""
    decision_status = PENDING
    if decision == "confirm":
        decision_status = CONFIRMED
    elif decision == "route":
        decision_status = ROUTED

    ev = f.get("evidence") or {}
    return {
        "kind": kind,
        "temporal_status": temporal,
        "decision_status": decision_status,
        "title": label,
        "meaning": meaning,
        "date": d,
        "basis": basis,
        "party": f.get("party", ""),
        "consequence": consequence,
        "fee": _fee(f.get("quote", ""), f.get("summary", "")),
        "page": ev.get("page"),
        "section": ev.get("section", ""),
        "tier": ev.get("tier"),
    }


def build_timeline(findings: list[dict[str, Any]], effective_date: str = "", expiration_date: str = "") -> tuple[list[dict[str, Any]], int]:
    active = [f for f in findings if f.get("decision") != "dismiss"]
    active, merged_count = dedup_findings(active)
    items: list[dict[str, Any]] = []
    for f in active:
        item = _classify(f, effective_date, expiration_date)
        if item is None:
            continue
        items.append({
            "id": f["id"],
            "kind": item["kind"],
            # status remains temporal; human decision is a separate field.
            "status": item["temporal_status"],
            "temporal_status": item["temporal_status"],
            "decision_status": item["decision_status"],
            "title": item["title"],
            "meaning": item["meaning"],
            "date": item["date"],
            "basis": item["basis"],
            "party": item["party"],
            "consequence": item["consequence"],
            "fee": item["fee"],
            "page": item["page"],
            "section": item["section"],
            "tier": item["tier"],
            "mergedLabels": f.get("mergedLabels", []),
        })
    rank = {OVERDUE: 0, DUE_SOON: 1, UPCOMING: 2, TRACKED: 3, RELATIVE: 4}
    items.sort(key=lambda x: (rank.get(x["temporal_status"], 9), x["date"] or "9999-99-99", x["kind"], x["title"]))
    return items, merged_count
