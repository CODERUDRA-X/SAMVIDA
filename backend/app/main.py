"""ContractLens API.

Endpoints mirror the agent's lifecycle rather than CRUD:
    POST /api/contracts              upload, parse, start the graph (runs to first interrupt)
    GET  /api/runs/{doc_id}          current agent state
    POST /api/runs/{doc_id}/decision record a human decision and resume the graph
    POST /api/contracts/{doc_id}/ask grounded natural-language question
"""
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from . import extract  # noqa: E402  (after load_dotenv so the key is present)
from .graph import GRAPH  # noqa: E402
from .pdf_parse import parse_pdf  # noqa: E402

app = FastAPI(title="ContractLens", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CONTRACTLENS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCS: dict[str, dict[str, Any]] = {}  # doc_id -> {file_name, pages}


def cfg(doc_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": doc_id}}


def snapshot(doc_id: str) -> dict[str, Any]:
    """Serialise agent state for the UI. Page words are never sent: too large."""
    st = GRAPH.get_state(cfg(doc_id))
    v = st.values or {}
    interrupted = bool(st.next)
    stage = v.get("stage", "IDLE")
    if interrupted and v.get("pending_id"):
        stage = "AWAITING_HUMAN_REVIEW"
    return {
        "docId": doc_id,
        "fileName": v.get("file_name", ""),
        "stage": stage,
        "interrupted": interrupted,
        "nextNodes": list(st.next),
        "pendingId": v.get("pending_id"),
        "parties": v.get("parties", {}),
        "effectiveDate": v.get("effective_date", ""),
        "expirationDate": v.get("expiration_date", ""),
        "findings": v.get("findings", []),
        "timeline": v.get("timeline", []),
        "audit": v.get("audit", []),
        "error": v.get("error"),
        "pageSizes": [
            {"page": p["page"], "width": p["width"], "height": p["height"]}
            for p in DOCS.get(doc_id, {}).get("pages", [])
        ],
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "model": extract.MODEL, "keyPresent": bool(os.environ.get("GEMINI_API_KEY"))}


@app.post("/api/contracts")
def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "ContractLens reads text-based PDF contracts. Upload a .pdf file.")
    data = file.file.read()
    try:
        pages = parse_pdf(data)
    except Exception as exc:
        raise HTTPException(422, f"That PDF could not be parsed: {exc}")

    chars = sum(len(p["text"]) for p in pages)
    if chars < 500:
        raise HTTPException(
            422,
            "Almost no selectable text was found. ContractLens needs a digital contract, not a scan or a photograph.",
        )

    doc_id = uuid.uuid4().hex[:12]
    DOCS[doc_id] = {"file_name": file.filename, "pages": pages}

    # run the graph; it stops on its own at the first high-risk finding
    GRAPH.invoke({"doc_id": doc_id, "file_name": file.filename, "pages": pages, "audit": []}, cfg(doc_id))
    return snapshot(doc_id)


@app.get("/api/runs/{doc_id}")
def get_run(doc_id: str) -> dict[str, Any]:
    if doc_id not in DOCS:
        raise HTTPException(404, "Unknown document.")
    return snapshot(doc_id)


class Decision(BaseModel):
    finding_id: str
    choice: str  # confirm | dismiss | route


@app.post("/api/runs/{doc_id}/decision")
def decide(doc_id: str, body: Decision) -> dict[str, Any]:
    if doc_id not in DOCS:
        raise HTTPException(404, "Unknown document.")
    if body.choice not in {"confirm", "dismiss", "route"}:
        raise HTTPException(400, "choice must be confirm, dismiss or route.")

    state = GRAPH.get_state(cfg(doc_id))
    if not state.next:
        raise HTTPException(409, "The agent is not waiting for a decision.")

    GRAPH.update_state(cfg(doc_id), {"decision": {"finding_id": body.finding_id, "choice": body.choice}})
    GRAPH.invoke(None, cfg(doc_id))  # resume from the checkpoint
    return snapshot(doc_id)


class Question(BaseModel):
    question: str


@app.post("/api/contracts/{doc_id}/ask")
def ask(doc_id: str, body: Question) -> dict[str, Any]:
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "Unknown document.")
    from .pdf_parse import full_text, ground_quote

    try:
        result = extract.answer_question(full_text(doc["pages"]), body.question)
    except extract.ExtractionError as exc:
        raise HTTPException(502, str(exc))
    if result["quote"]:
        result["evidence"] = ground_quote(doc["pages"], result["quote"], result.get("page"))
        result["page"] = result["evidence"].get("page")
    return result
