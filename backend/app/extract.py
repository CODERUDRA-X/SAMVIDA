"""Structured extraction and grounded Q&A through Gemini with honest fallbacks."""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from . import config
from .pdf_parse import Document, ground_quote
from .retrieval import HybridRetriever
from .verification import verify_finding

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class ExtractionError(RuntimeError):
    pass


SCHEMA = """Return ONLY JSON with this shape:
{"parties":{"customer":"","supplier":""},"effectiveDate":"","expirationDate":"",
 "findings":[{"label":"","summary":"","quote":"","page":1,"date":"","dateBasis":"","party":"","category":""}]}

Rules:
- quote MUST be verbatim source text, 15-900 characters, no ellipsis or paraphrase.
- page is the [PAGE n] block containing the quote.
- date is YYYY-MM-DD ONLY when an absolute date is actually stated or safely derivable from the quoted source.
- dateBasis preserves relative timing such as "75 days after invoice date" or "annually; no later than 30 June".
- party is Customer, Supplier, Both, or empty.
- category is term, renewal, payment, termination, service-level, obligation, data, liability.
- Do not invent legal conclusions, risk ratings, or missing dates.
- Keep the summary faithful to the quote; all numbers, fees, percentages and deadlines must be present in the quote.
"""


def model_name() -> str:
    return config.model_name()


def _api_key() -> str:
    key = config.api_key()
    if not key:
        raise ExtractionError("GEMINI_API_KEY is not set.")
    return key


def _json_call(prompt: str, max_tokens: int = 5000) -> dict[str, Any]:
    url = _ENDPOINT.format(model=model_name())
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
    }
    try:
        resp = requests.post(url, params={"key": _api_key()}, json=payload, timeout=90)
    except requests.RequestException as exc:
        raise ExtractionError(f"Could not reach Gemini: {exc}") from exc
    if resp.status_code == 429:
        raise ExtractionError("Gemini free-tier rate limit hit. Wait briefly and retry.")
    if not resp.ok:
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise ExtractionError(f"Gemini call failed ({resp.status_code}): {detail or resp.text[:250]}")
    body = resp.json()
    try:
        cand = body["candidates"][0]
        finish = cand.get("finishReason", "")
        text = "".join(p.get("text", "") for p in cand["content"]["parts"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        block = body.get("promptFeedback", {}).get("blockReason")
        raise ExtractionError(f"Gemini returned no usable content{f' ({block})' if block else ''}.") from exc
    if not text:
        raise ExtractionError("Gemini returned an empty reply.")
    for candidate in (text, _fenced(text), _braced(text)):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, TypeError):
            pass
    if finish == "MAX_TOKENS":
        raise ExtractionError("Gemini's reply was cut off before finishing.")
    raise ExtractionError("Gemini reply was not valid JSON.")


def _fenced(t: str) -> str:
    m = re.search(r"```(?:json)?\s*(.+?)```", t, re.S | re.I)
    return m.group(1).strip() if m else ""


def _braced(t: str) -> str:
    a, b = t.find("{"), t.rfind("}")
    return t[a:b + 1] if a >= 0 and b > a else ""


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {"term", "renewal", "payment", "termination", "service-level", "obligation", "data", "liability"}
    out = {
        "parties": data.get("parties") or {},
        "effectiveDate": str(data.get("effectiveDate") or "").strip(),
        "expirationDate": str(data.get("expirationDate") or "").strip(),
        "findings": [],
    }
    for idx, f in enumerate(data.get("findings") or []):
        if not isinstance(f, dict):
            continue
        quote = str(f.get("quote") or "").strip()
        if len(quote) < 15:
            continue
        category = str(f.get("category") or "obligation").strip().lower()
        if category not in allowed:
            category = "obligation"
        page = f.get("page") if isinstance(f.get("page"), int) else None
        out["findings"].append({
            "id": f"f{idx}",
            "label": str(f.get("label") or "Finding").strip(),
            "summary": str(f.get("summary") or "").strip(),
            "quote": quote,
            "page": page,
            "date": str(f.get("date") or "").strip(),
            "dateBasis": str(f.get("dateBasis") or "").strip(),
            "party": str(f.get("party") or "").strip(),
            "category": category,
            "decision": None,
            "source": "gemini",
        })
    return out


def _run_prompt(prompt: str, doc: Document) -> dict[str, Any]:
    if config.llm_enabled():
        return _clean(_json_call(prompt))
    if config.local_fallback_enabled():
        from .local_extract import extract as local_extract
        return local_extract(doc)
    raise ExtractionError("LLM is disabled and local fallback is disabled.")


def extract_core_terms(text: str, doc: Document | None = None) -> dict[str, Any]:
    if doc is None:
        raise ExtractionError("Document context is required for grounded extraction.")
    if not config.llm_enabled() and config.local_fallback_enabled():
        from .local_extract import extract as local_extract
        data = local_extract(doc)
        core_cats = {"term", "renewal", "payment", "termination"}
        data["findings"] = [f for f in data.get("findings", []) if f.get("category") in core_cats][:8]
        return data
    prompt = f"""You are extracting business-contract facts for an operations workspace.
Prioritize the parties, effective/expiry dates, term and renewal mechanics, payment terms,
price adjustment rights, and termination terms. Return 5-8 material findings. Do not duplicate
the same clause unless the second item adds a distinct obligation.
{SCHEMA}
CONTRACT:
{text}"""
    return _run_prompt(prompt, doc)


def extract_obligations(text: str, doc: Document | None = None) -> dict[str, Any]:
    if doc is None:
        raise ExtractionError("Document context is required for grounded extraction.")
    if not config.llm_enabled() and config.local_fallback_enabled():
        from .local_extract import extract as local_extract
        data = local_extract(doc)
        obligation_cats = {"service-level", "obligation", "data"}
        data["findings"] = [f for f in data.get("findings", []) if f.get("category") in obligation_cats][:10]
        # Core fields are intentionally not reused from the obligation pass.
        data["parties"], data["effectiveDate"], data["expirationDate"] = {}, "", ""
        return data
    prompt = f"""You are extracting operational obligations from a business contract.
Return 6-10 distinct deadline-bound, recurring, reporting, notice, security, service-level,
data-return or termination obligations. Avoid restating headline commercial terms unless a
person must perform an action. Keep relative deadlines relative; do not invent calendar dates.
{SCHEMA}
CONTRACT:
{text}"""
    return _run_prompt(prompt, doc)


def answer_question(doc: Document, question: str) -> dict[str, Any]:
    retriever = HybridRetriever(doc)
    context = retriever.context(question, k=10)
    prompt = f"""Answer the question using ONLY the source context below.
Return ONLY JSON: {{"answer":"","quote":"","page":1}}
The answer must be at most three sentences. quote must be copied verbatim from source context or
empty when the document does not support an answer. Never infer beyond the contract.
QUESTION: {question}
SOURCE CONTEXT:
{context}"""
    if config.llm_enabled():
        data = _json_call(prompt, max_tokens=1200)
    elif config.local_fallback_enabled():
        # Simple offline QA: surface the highest scoring source sentence.
        rows = retriever.search(question, k=1)
        if not rows:
            return {"answer": "The contract does not address that question.", "quote": "", "page": None}
        top = rows[0]
        return {"answer": top.sentence, "quote": top.sentence, "page": top.page}
    else:
        raise ExtractionError("LLM is disabled and local fallback is disabled.")

    result = {"answer": str(data.get("answer") or "").strip(), "quote": str(data.get("quote") or "").strip(), "page": data.get("page") if isinstance(data.get("page"), int) else None}
    if result["quote"]:
        ev = ground_quote(doc.pages, result["quote"], result["page"])
        result["evidence"] = ev
    return result


def verify_extraction(findings: list[dict[str, Any]], doc: Document) -> list[dict[str, Any]]:
    out = []
    from .pdf_parse import ground_quote
    for f in findings:
        ev = ground_quote(doc.pages, f.get("quote", ""), f.get("page"))
        g = dict(f)
        g["evidence"] = ev
        g = verify_finding(g, doc, ev)
        out.append(g)
    return out
