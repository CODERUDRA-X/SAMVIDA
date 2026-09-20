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

import requests

MODEL = os.environ.get("CONTRACTLENS_MODEL", "gemini-3.5-flash-lite")
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


def extract_core_terms(text: str) -> dict[str, Any]:
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


def extract_obligations(text: str) -> dict[str, Any]:
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


def answer_question(text: str, question: str) -> dict[str, Any]:
    data = _json_call(
        f"""Answer the question using ONLY the contract below.

Reply with ONLY JSON: {{"answer":"","quote":"","page":1}}
"answer" is at most three sentences. "quote" is copied verbatim from the contract and supports the
answer, or "" if nothing in the contract supports it. If the contract does not address the
question, say exactly that in "answer".

QUESTION: {question}

CONTRACT:
{text}""",
        max_tokens=1200,
    )
    return {
        "answer": (data.get("answer") or "").strip(),
        "quote": (data.get("quote") or "").strip(),
        "page": data.get("page") if isinstance(data.get("page"), int) else None,
    }
