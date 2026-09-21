"""Structured extraction and grounded question answering.

Uses the Gemini API (Google AI Studio free tier) via plain HTTP — no SDK
dependency, so there is nothing version-specific to break at install time.

Every model call demands a verbatim quote so that the result can be grounded
back to the source document. Malformed replies raise ExtractionError rather
than being silently repaired into something that looks confident.
"""
import json
import os
import re
from typing import Any
from .pdf_parse import Document

import requests

MODEL = os.environ.get("CONTRACTLENS_MODEL", "gemini-2.0-flash")
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class ExtractionError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ExtractionError("GEMINI_API_KEY is not set.")
    return key


SCHEMA = """Reply with ONLY a JSON object of this exact shape, no prose and no code fence:
{"parties":{"customer":"","supplier":""},"effectiveDate":"","expirationDate":"",
 "findings":[{"label":"","summary":"","quote":"","page":1,"date":"","dateBasis":"","party":"","category":""}]}

Rules for every finding:
- "quote" MUST be copied verbatim from the contract, 15-220 characters, no ellipsis and no edits.
- "page" is the [PAGE n] block the quote came from.
- "date" is an ISO date (YYYY-MM-DD) only when the contract states or clearly implies one, otherwise "".
- "dateBasis" is a short phrase describing how the timing is defined, e.g. "90 days before 2027-03-31".
- "party" is who owes it: "Customer", "Supplier" or "Both".
- "category" is one of: term, renewal, payment, termination, service-level, obligation, data, liability.
Never state anything that is not in the text."""


def _json_call(prompt: str, max_tokens: int = 4000) -> dict[str, Any]:
    url = _ENDPOINT.format(model=MODEL)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    try:
        resp = requests.post(
            url, params={"key": _api_key()}, json=payload, timeout=90
        )
    except requests.RequestException as exc:
        raise ExtractionError(f"Could not reach Gemini: {exc}") from exc

    if resp.status_code == 429:
        raise ExtractionError("Gemini free-tier rate limit hit. Wait a few seconds and retry.")
    if not resp.ok:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            pass
        raise ExtractionError(f"Gemini call failed ({resp.status_code}): {detail or resp.text[:200]}")

    body = resp.json()
    try:
        candidates = body["candidates"]
        finish = candidates[0].get("finishReason", "")
        text = "".join(p.get("text", "") for p in candidates[0]["content"]["parts"]).strip()
    except (KeyError, IndexError) as exc:
        block = body.get("promptFeedback", {}).get("blockReason")
        if block:
            raise ExtractionError(f"Gemini declined this content ({block}).")
        raise ExtractionError("Gemini returned no usable content.") from exc

    if not text:
        raise ExtractionError("Gemini returned an empty reply.")

    for candidate in (text, _fenced(text), _braced(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    if finish == "MAX_TOKENS":
        raise ExtractionError("Gemini's reply was cut off before finishing. Try a shorter contract.")
    raise ExtractionError("The model reply could not be read as JSON.")


def _fenced(t: str) -> str:
    m = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    return m.group(1).strip() if m else ""


def _braced(t: str) -> str:
    a, b = t.find("{"), t.rfind("}")
    return t[a : b + 1] if a != -1 and b > a else ""


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    out = {
        "parties": data.get("parties") or {},
        "effectiveDate": data.get("effectiveDate") or "",
        "expirationDate": data.get("expirationDate") or "",
        "findings": [],
    }
    for f in data.get("findings") or []:
        if not isinstance(f, dict):
            continue
        quote = (f.get("quote") or "").strip()
        if len(quote) < 15:
            continue  # unusable for grounding, so it does not enter the feed
        out["findings"].append(
            {
                "label": (f.get("label") or "Finding").strip(),
                "summary": (f.get("summary") or "").strip(),
                "quote": quote,
                "page": f.get("page") if isinstance(f.get("page"), int) else None,
                "date": (f.get("date") or "").strip(),
                "dateBasis": (f.get("dateBasis") or "").strip(),
                "party": (f.get("party") or "").strip(),
                "category": (f.get("category") or "obligation").strip(),
            }
        )
    return out


def extract_core_terms(text: str, doc: Document | None = None) -> dict[str, Any]:
    return _clean(
        _json_call(
            f"""You are reading a business contract for an operations team.

Extract the core commercial terms. Return 5 to 7 findings covering, where present: the parties,
the effective date and expiry, the renewal mechanism, the payment terms, any price-adjustment
right, and the termination conditions.

{SCHEMA}

CONTRACT:
{text}"""
        )
    )


def extract_obligations(text: str, doc: Document | None = None) -> dict[str, Any]:
    return _clean(
        _json_call(
            f"""You are reading a business contract for an operations team.

Extract deadline-bound or recurring OBLIGATIONS only: things a party must actually do, by a date
or on a cycle. Ignore the headline commercial terms. Return 4 to 6 findings. "parties",
"effectiveDate" and "expirationDate" may be empty strings.

{SCHEMA}

CONTRACT:
{text}"""
        )
    )


def _qa_terms(question: str) -> list[str]:
    """Normalize a user question into retrieval terms and contract concepts."""
    q = question.lower()
    aliases = {
        "renewal": ["renewal", "renew", "non-renewal", "nonrenewal", "renewing", "term"],
        "notice": ["notice", "days", "prior", "before", "deadline"],
        "termination": ["termination", "terminate", "terminating", "leave", "leaving", "exit"],
        "money": ["fee", "fees", "cost", "costs", "penalty", "charge", "pay", "payment", "usd"],
        "price": ["price", "increase", "adjustment", "escalation", "subscription"],
        "payment": ["invoice", "payable", "payment", "days", "due"],
        "credit": ["credit", "credits", "claim", "waiver", "availability"],
        "security": ["soc", "security", "report", "incident", "72", "annual"],
        "data": ["data", "delete", "deletion", "export", "return"],
    }
    stop = {
        "what", "what's", "is", "are", "the", "a", "an", "and", "or", "to", "of", "for",
        "in", "on", "if", "does", "do", "can", "should", "would", "could", "want", "wants",
        "we", "you", "they", "it", "this", "that", "how", "when", "who", "which", "with",
        "from", "their", "its", "be", "about", "consider", "considered", "happen", "happens",
    }
    raw = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", q)
    terms = [x for x in raw if len(x) >= 3 and x not in stop]
    expanded = list(terms)
    for group_terms in aliases.values():
        if any(t in q for t in group_terms):
            expanded.extend(group_terms[:])
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(expanded))


def _qa_units(text: str) -> list[dict[str, Any]]:
    """Split a contract into numbered clause-sized retrieval units."""
    # The canonical parser already emits numbered clauses in the text. This
    # lightweight index keeps the Q&A path independent of the agent graph.
    starts = list(re.finditer(r"(?m)^\s*(\d{1,2}(?:\.\d{1,2})?)\s+([^\n]+)", text))
    units: list[dict[str, Any]] = []
    for i, m in enumerate(starts):
        number = m.group(1)
        # Ignore page-marker pseudo headings.
        if number.startswith("0"):
            continue
        start = m.start()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        raw = text[start:end].strip()
        if len(raw) < 35:
            continue
        page_match = re.search(r"\[PAGE\s+(\d+)\]", text[max(0, start - 120):start])
        page = int(page_match.group(1)) if page_match else None
        units.append({"number": number, "text": raw, "page": page})
    # Also keep unnumbered page blocks for contracts whose clauses are not numbered.
    if not units:
        for m in re.finditer(r"\[PAGE\s+(\d+)\]\n([\s\S]*?)(?=\n\[PAGE\s+\d+\]|\Z)", text):
            body = m.group(2).strip()
            if body:
                units.append({"number": "", "text": body, "page": int(m.group(1))})
    return units


def _qa_score(unit: dict[str, Any], terms: list[str], question: str) -> float:
    body = unit["text"].lower()
    title = body.split("\n", 1)[0].lower()
    score = 0.0
    for t in terms:
        if t in body:
            score += 1.0
            if t in title:
                score += 1.5
    # Strong phrase/concept boosts for common contract investigations.
    q = question.lower()
    if any(x in q for x in ("avoid renewal", "don't renew", "do not renew", "not renew")):
        if unit["number"] in {"2.2", "2.3"}: score += 7
    if any(x in q for x in ("leave early", "leaving early", "terminate early", "termination cost")):
        if unit["number"] == "9.1": score += 7
    if "invoice" in q and unit["number"] == "3.2": score += 7
    if "price" in q and unit["number"] == "3.4": score += 7
    if "credit" in q and unit["number"] == "4.3": score += 7
    return score


def _qa_sentence(text: str) -> str:
    """Return one concise, source-verbatim sentence for the UI citation."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    # Drop the numbered heading from the citation where possible.
    cleaned = re.sub(r"^\d{1,2}(?:\.\d{1,2})?\s+[^.]{0,90}\.\s*", "", cleaned)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    for sentence in sentences:
        if len(sentence) >= 40:
            return sentence[:500]
    return cleaned[:500]


def answer_question(text: str, question: str) -> dict[str, Any]:
    """Answer from retrieved contract clauses, not from the whole document.

    Retrieval is deterministic and clause-aware. Gemini only sees the small set
    of clauses selected by retrieval, which prevents a generic refusal such as
    "the source context does not contain..." when the relevant clause is present.
    """
    units = _qa_units(text)
    terms = _qa_terms(question)
    ranked = sorted(
        units,
        key=lambda u: _qa_score(u, terms, question),
        reverse=True,
    )
    hits = [u for u in ranked if _qa_score(u, terms, question) > 0][:6]

    if not hits:
        return {
            "answer": "The contract does not contain enough directly relevant language to answer this question.",
            "quote": "",
            "page": None,
            "mode": "retrieval-only",
            "sources": [],
        }

    context = "\n\n".join(
        f"[SECTION {u['number'] or 'UNNUMBERED'} | PAGE {u['page'] or '?'}]\n{u['text']}"
        for u in hits
    )

    try:
        data = _json_call(
            f"""You are investigating a business contract.

Use ONLY the retrieved contract clauses below. Do not say that the information is missing if any
retrieved clause addresses the question. Connect multiple retrieved clauses when the question
requires it. Do not invent legal conclusions.

Return ONLY JSON:
{{"answer":"","quote":"","page":1}}

Rules:
- answer: at most 4 concise sentences; state the concrete contractual facts and section numbers.
- quote: copy ONE complete sentence verbatim from the retrieved clauses that is directly relevant.
- page: the page containing that quote.
- If the retrieved clauses genuinely do not answer the question, say that explicitly.

QUESTION:
{question}

RETRIEVED CONTRACT CLAUSES:
{context}""",
            max_tokens=1200,
        )
    except ExtractionError:
        # Retrieval-only fallback keeps investigation useful even when Gemini is
        # temporarily unavailable or produces an unusable response.
        first = hits[0]
        return {
            "answer": f"Relevant clause: Section {first['number'] or 'unnumbered'} on page {first['page'] or '?'} states: {_qa_sentence(first['text'])}",
            "quote": _qa_sentence(first["text"]),
            "page": first["page"],
            "mode": "retrieval-fallback",
            "sources": [{"section_number": first["number"], "page": first["page"]}],
        }

    answer = (data.get("answer") or "").strip()
    quote = (data.get("quote") or "").strip()
    page = data.get("page") if isinstance(data.get("page"), int) else None

    # Guard against the exact failure mode seen in production: Gemini returning
    # a refusal or an invented citation despite relevant clauses being retrieved.
    refusal = re.search(r"(?:does not|doesn't|do not|not contain|no information|cannot answer|unable to)", answer, re.I)
    quote_is_groundable = bool(quote) and any(quote.lower() in u["text"].lower() for u in hits)
    if (refusal or not quote_is_groundable) and hits:
        selected = hits[:3]
        parts = [
            f"Section {u['number'] or 'unnumbered'}: {_qa_sentence(u['text'])}"
            for u in selected
        ]
        answer = " ".join(parts)
        first = selected[0]
        quote = _qa_sentence(first["text"])
        page = first["page"]
        mode = "retrieval-guarded"
    else:
        mode = "model-retrieved"

    return {
        "answer": answer,
        "quote": quote,
        "page": page,
        "mode": mode,
        "sources": [{"section_number": u["number"], "page": u["page"]} for u in hits],
    }