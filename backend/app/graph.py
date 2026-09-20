"""The ContractLens agent as an explicit LangGraph state machine.

    parse -> extract_obligations -> evaluate_risk -> ground_evidence -> checkpoint
    checkpoint --(high risk pending)--> [INTERRUPT] human_intervention -> checkpoint
    checkpoint --(nothing pending)---> finalize -> END

The pause is real: the graph is compiled with interrupt_before=["human_intervention"],
so execution stops inside the checkpointer and the run only continues when the API
writes a decision into state and re-invokes the graph.
"""
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from . import extract, risk
from .pdf_parse import full_text, ground_quote


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
    audit: Annotated[list[dict[str, Any]], lambda a, b: (a or []) + (b or [])]
    pending_id: str | None
    decision: dict[str, Any] | None
    stage: str
    error: str | None


def _event(what: str, detail: str = "") -> dict[str, Any]:
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "what": what, "detail": detail}


# --------------------------------------------------------------------------- nodes

def node_parse(state: AgentState) -> dict[str, Any]:
    pages = state["pages"]
    text = full_text(pages)
    return {
        "contract_text": text,
        "stage": "PARSED",
        "audit": [_event("Contract parsed", f"{len(pages)} pages, {len(text):,} characters of extractable text")],
    }


def node_extract(state: AgentState) -> dict[str, Any]:
    text = state["contract_text"]
    audit = []
    findings: list[dict[str, Any]] = []
    parties, eff, exp = {}, "", ""

    try:
        core = extract.extract_core_terms(text)
        parties = core.get("parties") or {}
        eff, exp = core.get("effectiveDate", ""), core.get("expirationDate", "")
        findings += core["findings"]
        audit.append(_event("Commercial terms extracted", f"{len(core['findings'])} findings"))
    except extract.ExtractionError as exc:
        return {"stage": "ERROR", "error": str(exc), "audit": [_event("Extraction failed", str(exc))]}

    try:
        obl = extract.extract_obligations(text)
        findings += obl["findings"]
        audit.append(_event("Obligations extracted", f"{len(obl['findings'])} findings"))
    except extract.ExtractionError as exc:
        # partial success is honest: keep the core terms, record the gap
        audit.append(_event("Obligation extraction failed", str(exc)))

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
    high = sum(1 for f in findings if f["risk"] == risk.HIGH)
    return {
        "findings": findings,
        "stage": "EVALUATED",
        "audit": [_event("Risk rules applied", f"{high} high-risk of {len(findings)} findings")],
    }


def node_ground(state: AgentState) -> dict[str, Any]:
    pages = state["pages"]
    findings = []
    for f in state.get("findings", []):
        g = dict(f)
        g["evidence"] = ground_quote(pages, g.get("quote", ""), g.get("page"))
        g["page"] = g["evidence"].get("page") or g.get("page")
        findings.append(g)
    t1 = sum(1 for f in findings if f["evidence"]["tier"] == 1)
    return {
        "findings": findings,
        "stage": "GROUNDED",
        "audit": [_event("Source evidence attached", f"{t1} exact passages, {len(findings) - t1} page references")],
    }


def node_checkpoint(state: AgentState) -> dict[str, Any]:
    pending = next((f for f in state.get("findings", []) if risk.requires_intervention(f)), None)
    if pending:
        return {
            "pending_id": pending["id"],
            "stage": "AWAITING_HUMAN_REVIEW",
            "audit": [
                _event(
                    "Execution paused",
                    f"{pending.get('ruleId', 'rule')} fired on \"{pending['label']}\" — human verification required",
                )
            ],
        }
    return {"pending_id": None, "stage": "CHECKPOINT_CLEAR"}


def node_human_intervention(state: AgentState) -> dict[str, Any]:
    """Applies the decision the API wrote into state, then hands back to checkpoint."""
    decision = state.get("decision") or {}
    fid, choice = decision.get("finding_id"), decision.get("choice")
    findings = []
    label = ""
    for f in state.get("findings", []):
        g = dict(f)
        if g["id"] == fid:
            g["decision"] = choice
            g["decided_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            label = g["label"]
        findings.append(g)
    return {
        "findings": findings,
        "decision": None,
        "pending_id": None,
        "stage": "RESUMING",
        "audit": [_event("Human decision recorded", f"{choice} — \"{label}\"")],
    }


def node_finalize(state: AgentState) -> dict[str, Any]:
    timeline = []
    for f in state.get("findings", []):
        if f.get("decision") == "dismiss":
            continue
        if not (f.get("date") or f.get("dateBasis") or f["risk"] == risk.HIGH or f["category"] == "obligation"):
            continue
        ev = f.get("evidence") or {}
        timeline.append(
            {
                "id": f["id"],
                "label": f["label"],
                "date": f.get("date", ""),
                "basis": f.get("dateBasis", ""),
                "party": f.get("party", ""),
                "page": ev.get("page"),
                "section": ev.get("section", ""),
                "risk": f["risk"],
                "status": "ROUTED FOR REVIEW" if f.get("decision") == "route"
                else ("CONFIRMED" if f.get("decision") == "confirm" else "TRACKED"),
            }
        )
    timeline.sort(key=lambda t: (t["date"] == "", t["date"]))
    return {
        "timeline": timeline,
        "stage": "COMPLETED",
        "audit": [_event("Action timeline updated", f"{len(timeline)} tracked actions")],
    }


# --------------------------------------------------------------------------- wiring

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

    # the pause is enforced by the graph itself, not by the frontend
    return b.compile(checkpointer=MemorySaver(), interrupt_before=["human_intervention"])


GRAPH = build_graph()
