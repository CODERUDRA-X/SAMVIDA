"""Runtime configuration for ContractLens.

Values are resolved lazily so tests, local demos and .env edits do not require
re-importing modules. No credential is stored in source control.
"""
from __future__ import annotations

import os
from datetime import date

DEFAULT_MODEL = "gemini-3.5-flash-lite"


def model_name() -> str:
    return os.environ.get("CONTRACTLENS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def llm_enabled() -> bool:
    return bool(api_key()) and os.environ.get("CONTRACTLENS_OFFLINE", "").lower() not in {"1", "true", "yes"}


def local_fallback_enabled() -> bool:
    return os.environ.get("CONTRACTLENS_LOCAL_FALLBACK", "1").lower() not in {"0", "false", "no"}


def today() -> date:
    raw = os.environ.get("CONTRACTLENS_TODAY", "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()
