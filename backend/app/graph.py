"""Stateful ContractLens agent graph with a real human checkpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from . import extract, risk, reasoning, timeline
from .knowledge_graph import build_knowledge_graph
from .pdf_parse import Document, full_text, ground_quote
from .verification import verify_finding


class AgentState(TypedDict, total=False):
    doc_id: str
    file_name: str
    pages: list[dict[str, Any]]
    contract_text: str
    parties: dict[str, str]
    effective_date: str
    expiration_date: str
    findings: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    insights: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]
    audit: Annotated[list[dict[str, Any]], lambda a, b: (a or []) + (b or [])]
    pending_id: str | None
    decision: dict[str, Any] | None
    stage: str
    error: str | None


def _event(what: str, detail: str = "") -> dict[str, Any]:
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "what": what, "detail": detail}


def node_parse(state: AgentState) -> dict[str, Any]:
    pages = state["pages"]
    text = full_text(pages)
    return {"contract_text": text, "stage": "PARSED", "audit": [_event("Contract parsed", f"{len(pages)} pages, {len(text):,} characters of extractable text")]}


def node_extract(state: AgentState) -> dict[str, Any]:
    doc = Document.from_pages(state["pages"])
    text = state["contract_text"]
    findings: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    parties: dict[str, str] = {}
    eff = exp = ""

    try:
        core = extract.extract_core_terms(text, doc)
        parties = core.get("parties") or {}
        eff, exp = core.get("effectiveDate", ""), core.get("expirationDate", "")
        findings.extend(core.get("findings", []))
        audit.append(_event("Commercial terms extracted", f"{len(core.get('findings', []))} findings via {core.get('findings', [{}])[0].get('source', 'model') if core.get('findings') else 'model'}"))
    except extract.ExtractionError as exc:
        return {"stage": "ERROR", "error": str(exc), "audit": [_event("Extraction failed", str(exc))]}

    try:
        obl = extract.extract_obligations(text, doc)
        findings.extend(obl.get("findings", []))
        audit.append(_event("Operational obligations extracted", f"{len(obl.get('findings', []))} findings"))
    except extract.ExtractionError as exc:
        # Core commercial terms remain visible; the audit trail records the gap.
        audit.append(_event("Obligation extraction failed", str(exc)))

    # Re-index deterministically. Decisions survive graph resumes because ids do not change.
    for i, f in enumerate(findings):
        f["id"] = f"f{i}"
        f["decision"] = None

    return {
        "findings": findings,
        "parties": parties,
        "effective_date": eff,
        "expiration_date": exp,
        "stage": "EXTRACTED",
        "audit": audit,
    }


def node_evaluate_risk(state: AgentState) -> dict[str, Any]:
    findings = [risk.assess(dict(f)) for f in state.get("findings", [])]
    high = sum(1 for f in findings if f.get("risk") == risk.HIGH)
    return {"findings": findings, "stage": "EVALUATED", "audit": [_event("Deterministic review policy applied", f"{high} high-review findings of {len(findings)} total")]}


def node_ground(state: AgentState) -> dict[str, Any]:
    doc = Document.from_pages(state["pages"])
    grounded: list[dict[str, Any]] = []
    for f in state.get("findings", []):
        g = dict(f)
        ev = ground_quote(state["pages"], g.get("quote", ""), g.get("page"))
        g["evidence"] = ev
        g["page"] = ev.get("page") or g.get("page")
        g = verify_finding(g, doc, ev)
        grounded.append(g)

    kg = build_knowledge_graph(doc)
    insights = reasoning.analyze(doc, kg)
    graph_edges = [{"src": e.src, "rel": e.rel, "dst": e.dst, "evidence": e.evidence} for e in kg.edges]
    exact = sum(1 for f in grounded if (f.get("evidence") or {}).get("tier") == 1)
    unsupported = sum(1 for f in grounded if f.get("verification_status") in {"INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"})
    return {
        "findings": grounded,
        "insights": insights,
        "graph_edges": graph_edges,
        "stage": "GROUNDED",
        "audit": [
            _event("Source evidence attached", f"{exact} exact word-level passages, {len(grounded)-exact} page/section fallbacks"),
            _event("Verification checks completed", f"{unsupported} findings need evidence review"),
            _event("Cross-clause relationships analyzed", f"{len(graph_edges)} explicit edges, {len(insights)} potential interactions"),
        ],
    }


def node_checkpoint(state: AgentState) -> dict[str, Any]:
    candidates = [f for f in state.get("findings", []) if risk.requires_intervention(f)]
    if candidates:
        pending = sorted(candidates, key=risk.pending_priority)[0]
        return {
            "pending_id": pending["id"],
            "stage": "AWAITING_HUMAN_REVIEW",
            "audit": [_event("Execution paused", f"{pending.get('ruleId', 'rule')} fired on \"{pending.get('label', 'finding')}\" — waiting for human direction")],
        }
    return {"pending_id": None, "stage": "CHECKPOINT_CLEAR"}


def _renewal_family(f: dict[str, Any]) -> bool:
    ev = f.get("evidence") or {}
    sec = str(ev.get("section_number") or "")
    hay = f"{f.get('label','')} {f.get('summary','')} {f.get('quote','')}".lower()
    return f.get("category") == "renewal" and (sec.startswith("2.") or "non-renewal" in hay or "automatic renewal" in hay or "perpetual" in hay)


def node_human_intervention(state: AgentState) -> dict[str, Any]:
    decision = state.get("decision") or {}
    fid, choice = decision.get("finding_id"), decision.get("choice")
    if fid != state.get("pending_id") or choice not in {"confirm", "dismiss", "route"}:
        raise ValueError("Decision does not match the pending human checkpoint.")

    pending = next((f for f in state.get("findings", []) if f.get("id") == fid), None)
    if not pending:
        raise ValueError("Pending finding no longer exists.")

    findings = []
    label = pending.get("label", "finding")
    linked = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for f in state.get("findings", []):
        g = dict(f)
        same_family = bool(pending.get("ruleId") == "R1-AUTO-RENEWAL" and _renewal_family(pending) and _renewal_family(g))
        if g.get("id") == fid or same_family:
            g["decision"] = choice
            g["decided_at"] = now
            if g.get("id") != fid:
                linked.append(g.get("label", "related finding"))
        findings.append(g)

    detail = f"{choice} — \"{label}\"; graph resumed"
    if linked:
        detail += f"; linked renewal evidence resolved: {', '.join(linked[:2])}"
    return {
        "findings": findings,
        "decision": None,
        "pending_id": None,
        "stage": "RESUMING",
        "audit": [_event("Human decision recorded", detail)],
    }


def node_finalize(state: AgentState) -> dict[str, Any]:
    items, merged_count = timeline.build_timeline(state.get("findings", []), state.get("effective_date", ""), state.get("expiration_date", ""))
    events: list[dict[str, Any]] = []
    if merged_count:
        events.append(_event("Duplicate findings merged", f"{merged_count} overlapping extraction records consolidated"))
    events.append(_event("Action timeline updated", f"{len(items)} entries; temporal and human decision status remain separate"))
    return {"timeline": items, "stage": "COMPLETED", "audit": events}


def _route(state: AgentState) -> str:
    return "human_intervention" if state.get("pending_id") else "finalize"


def build_graph():
    b = StateGraph(AgentState)
    b.add_node("parse", node_parse)
    b.add_node("extract_obligations", node_extract)
    b.add_node("evaluate_risk", node_evaluate_risk)
    b.add_node("ground_evidence", node_ground)
    b.add_node("checkpoint", node_checkpoint)
    b.add_node("human_intervention", node_human_intervention)
    b.add_node("finalize", node_finalize)
    b.set_entry_point("parse")
    b.add_edge("parse", "extract_obligations")
    b.add_edge("extract_obligations", "evaluate_risk")
    b.add_edge("evaluate_risk", "ground_evidence")
    b.add_edge("ground_evidence", "checkpoint")
    b.add_conditional_edges("checkpoint", _route, {"human_intervention": "human_intervention", "finalize": "finalize"})
    b.add_edge("human_intervention", "checkpoint")
    b.add_edge("finalize", END)
    return b.compile(checkpointer=MemorySaver(), interrupt_before=["human_intervention"])


GRAPH = build_graph()
