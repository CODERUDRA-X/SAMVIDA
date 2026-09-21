"""FastAPI surface for the ContractLens agent lifecycle."""
from __future__ import annotations

import os
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

from . import config, extract  # noqa: E402
from .graph import GRAPH  # noqa: E402
from .pdf_parse import Document, full_text, ground_quote, parse_pdf  # noqa: E402

app = FastAPI(title="SAMVIDA — Contract-to-Action Intelligence Agent", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in os.environ.get("CONTRACTLENS_ORIGINS", "http://localhost:5173").split(",") if x.strip()], allow_methods=["*"], allow_headers=["*"])

DOCS: dict[str, dict[str, Any]] = {}


def cfg(doc_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": doc_id}}


def snapshot(doc_id: str) -> dict[str, Any]:
    st = GRAPH.get_state(cfg(doc_id))
    v = st.values or {}
    interrupted = bool(st.next)
    stage = v.get("stage", "IDLE")
    if interrupted and v.get("pending_id"):
        stage = "AWAITING_HUMAN_REVIEW"
    return {
        "docId": doc_id,
        "fileName": v.get("file_name", DOCS.get(doc_id, {}).get("file_name", "")),
        "stage": stage,
        "interrupted": interrupted,
        "nextNodes": list(st.next),
        "pendingId": v.get("pending_id"),
        "parties": v.get("parties", {}),
        "effectiveDate": v.get("effective_date", ""),
        "expirationDate": v.get("expiration_date", ""),
        "findings": v.get("findings", []),
        "timeline": v.get("timeline", []),
        "insights": v.get("insights", []),
        "graphEdges": v.get("graph_edges", []),
        "audit": v.get("audit", []),
        "error": v.get("error"),
        "pageSizes": [{"page": p["page"], "width": p["width"], "height": p["height"]} for p in DOCS.get(doc_id, {}).get("pages", [])],
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "model": config.model_name(), "keyPresent": bool(config.api_key()), "offline": not config.llm_enabled()}


@app.post("/api/contracts")
def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "ContractLens reads text-based PDF contracts. Upload a .pdf file.")
    data = file.file.read()
    try:
        pages = parse_pdf(data)
    except Exception as exc:
        raise HTTPException(422, f"That PDF could not be parsed: {exc}") from exc
    chars = sum(len(p["text"]) for p in pages)
    if chars < 500:
        raise HTTPException(422, "Almost no selectable text was found. ContractLens needs a digital contract, not a scan or photograph.")
    doc_id = uuid.uuid4().hex[:12]
    DOCS[doc_id] = {"file_name": file.filename, "pages": pages}
    try:
        GRAPH.invoke({"doc_id": doc_id, "file_name": file.filename, "pages": pages, "audit": []}, cfg(doc_id))
    except Exception as exc:
        # Preserve a useful API error without leaking internals into the UI.
        raise HTTPException(502, f"The agent could not process this contract: {exc}") from exc
    return snapshot(doc_id)


@app.get("/api/runs/{doc_id}")
def get_run(doc_id: str) -> dict[str, Any]:
    if doc_id not in DOCS:
        raise HTTPException(404, "Unknown document.")
    return snapshot(doc_id)


class Decision(BaseModel):
    finding_id: str = Field(min_length=1)
    choice: str


@app.post("/api/runs/{doc_id}/decision")
def decide(doc_id: str, body: Decision) -> dict[str, Any]:
    if doc_id not in DOCS:
        raise HTTPException(404, "Unknown document.")
    if body.choice not in {"confirm", "dismiss", "route"}:
        raise HTTPException(400, "choice must be confirm, dismiss or route.")
    state = GRAPH.get_state(cfg(doc_id))
    pending = (state.values or {}).get("pending_id")
    if not state.next or not pending:
        raise HTTPException(409, "The agent is not waiting for a decision.")
    if pending != body.finding_id:
        raise HTTPException(409, "The selected finding is not the active checkpoint.")
    GRAPH.update_state(cfg(doc_id), {"decision": {"finding_id": body.finding_id, "choice": body.choice}})
    try:
        GRAPH.invoke(None, cfg(doc_id))
    except Exception as exc:
        raise HTTPException(502, f"The agent could not resume: {exc}") from exc
    return snapshot(doc_id)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@app.post("/api/contracts/{doc_id}/ask")
def ask(doc_id: str, body: Question) -> dict[str, Any]:
    doc_info = DOCS.get(doc_id)
    if not doc_info:
        raise HTTPException(404, "Unknown document.")
    try:
        result = extract.answer_question(full_text(doc_info["pages"]), body.question.strip())
        if result.get("quote"):
            result["evidence"] = ground_quote(
                doc_info["pages"],
                result["quote"],
                result.get("page"),
            )
            result["page"] = result["evidence"].get("page") or result.get("page")
        return result
    except extract.ExtractionError as exc:
        raise HTTPException(502, str(exc)) from exc
