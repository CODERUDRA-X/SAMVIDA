<div align="center">

# SAMVIDA
### Contract-to-Action Intelligence Agent

**Turns a business contract from a static PDF into a verifiable, source-grounded action plan — and knows exactly when to stop and ask a human.**

![Python](https://img.shields.io/badge/python-3.11%20%E2%80%93%203.14-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/node-%E2%89%A522.12-339933?logo=node.js&logoColor=white)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-1C3C3C)
![React](https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB?logo=react&logoColor=black)
![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)

Built for **Problem Statement 4 — Business Contract Review & Obligation Tracking** · Product Space **Agentic AI Hackathon 2026**

</div>

---

## The problem

Business contracts hide their most expensive sentences in plain sight. A perpetual auto-renewal clause on page 1, a 75-day payment term on page 2, a $45,000 exit fee on page 3 — nobody re-reads a 40-page SaaS agreement before the deadline that matters, until it's too late.

Generic "Chat with PDF" tools don't fix this. They wait for a question. They don't know which clause is dangerous. And when they're wrong, there's no way to tell.

## What SAMVIDA does instead

SAMVIDA doesn't wait to be asked. Upload a contract and the agent starts reading immediately — extracting obligations, mapping every finding back to an exact sentence in the source, and running a deterministic risk policy against what it found.

When it hits something genuinely high-stakes — an automatic renewal, an early-termination fee, a payment term outside normal range — **it stops.** Not a spinner. A real, backend-enforced pause in a LangGraph state machine, waiting for a human to Confirm, Dismiss, or Route it for review before the workflow continues.

That's the whole differentiator in one sentence: **the agent's intelligence is proven by what it refuses to do autonomously, not by what it does.**

---

## What makes this different from another ChatPDF clone

| Generic contract chatbot | SAMVIDA |
|---|---|
| Waits for a prompt | Starts reading the moment you upload |
| "Trust me" summaries | Every finding cites the exact source sentence, proven against a page/section |
| One-shot LLM call | 7-node LangGraph state machine with a genuine `interrupt_before` checkpoint |
| Silent on risk | Deterministic, inspectable rule engine — you can point to *which rule* fired and why |
| No way to check the model's work | A separate deterministic verification pass flags number/date conflicts between the claim and the quote |
| One evidence path that breaks silently | Two-tier evidence: exact bounding-box highlight, or page+section+excerpt fallback — never a dead end |
| Dies without an API key | Deterministic local extractor keeps the whole pipeline running offline |
| "It worked when I demoed it" | Six pytest cases assert exact section numbers, exact fees, and exact temporal states against the real demo contract |

---

## Architecture

```
                         CONTRACT (PDF)
                              |
                              v
                  +-----------------------+
                  |  Layout-aware parser  |   PyMuPDF word boxes ->
                  |  Document -> Clause   |   numbered clause hierarchy
                  +-----------+-----------+
                              |
              +---------------+---------------+
              v                               v
   +----------------------+         +-----------------------+
   |  Hybrid retrieval     |         |  Knowledge graph       |
   |  lexical + section +  |         |  REQUIRES_NOTICE,      |
   |  phrase + proximity   |         |  HAS_DEADLINE,         |
   +-----------+-----------+         |  CONDITIONAL_ON, ...   |
              |                     +-----------+-----------+
              v                                 v
       +-----------------------------------------------+
       |         Gemini extraction (or local            |
       |      deterministic fallback if offline)        |
       +----------------------+--------------------------+
                               v
                     Deterministic verification
                (quote grounding . number/date conflicts)
                               |
                               v
                    Deterministic risk policy (R1-R5)
                               |
                     +---------+---------+
                    safe               high-risk
                     |                    |
                     v                    v
                 CONTINUE          PAUSE -- real LangGraph
                     |                interrupt_before()
                     |                    |
                     |           +--------+--------+
                     |        CONFIRM  DISMISS   ROUTE
                     |           |
                     |           v
                     |        RESUME
                     +---------+-+
                               v
                    Bounded cross-clause reasoning
                    ("potential interaction", never
                     framed as a legal conclusion)
                               |
                               v
                  +------------+------------+
                  v                         v
           ACTION TIMELINE             AUDIT TRAIL
      (kind x temporal status x    (every real state
       decision status -- kept      transition, not a
       independent, on purpose)     feed duplicate)
```

### The state machine is real, not a frontend illusion

```python
b.compile(checkpointer=MemorySaver(), interrupt_before=["human_intervention"])
```

`parse -> extract_obligations -> evaluate_risk -> ground_evidence -> checkpoint -> [INTERRUPT] -> human_intervention -> checkpoint -> finalize`

When the agent pauses, `GET /api/runs/{doc_id}` genuinely reports `interrupted: true` with `human_intervention` as the next node — before any frontend code renders a single pixel. The decision endpoint validates that the finding a client submits actually matches the graph's own `pending_id`; a stale or spoofed finding ID is rejected with a 409, not silently accepted.

---

## Research-grade techniques — and exactly what's actually running

No technique below is decorative. Every row is imported and executed on the real request path — not a slide, not an unused module.

| Technique | What it actually does here | Status |
|---|---|---|
| **Layout-aware document model** | `Document -> Clause -> SourceSpan` hierarchy built from PyMuPDF word boxes; every clause carries a stable section number and title | Active |
| **Position-based source grounding** | Finds a quote's real character offset in the page, then walks backward to the nearest true heading — not a first-word keyword match that can land in the wrong section | Active |
| **Two-tier evidence** | Tier 1: exact word-level bounding boxes. Tier 2: page + section + excerpt when spatial mapping can't be proven. No fake boxes, ever. | Active |
| **Hybrid clause retrieval** | Lexical overlap + section/title overlap + exact phrase match + source proximity — deterministic parent-child retrieval without pretending to run embeddings it isn't running | Active |
| **Lightweight clause knowledge graph** | 14 explicit relation types (`REQUIRES_NOTICE`, `HAS_DEADLINE`, `CONDITIONAL_ON`, `SURVIVES_TERMINATION`, `INDEMNIFIES`, ...) — an edge only exists when source text supports it | Active, asserted in tests |
| **Bounded cross-clause reasoning** | Surfaces relationships single-clause extraction misses (e.g. renewal <-> notice window); output is always labeled a *potential interaction*, never a legal conclusion | Active |
| **Deterministic chain-of-verification** | Every finding is checked for source grounding and number/date consistency against its own quote, returning `SUPPORTED` / `PARTIALLY_SUPPORTED` / `INSUFFICIENT_EVIDENCE` / `CONFLICTING_EVIDENCE` | Active |
| **Deterministic risk policy** | 5 explicit, inspectable rules (auto-renewal, payment >60 days, exit fee, notice >=60 days, price escalation) decide the pause — never an unexplained "the model felt uneasy" | Active |
| **Temporal/decision status separation** | A confirmed finding whose deadline has passed still shows `OVERDUE` — confirming a finding is not the same as the obligation being met | Active, regression-tested |
| **Deterministic local fallback** | Runs the entire pipeline without Gemini for offline demos or API outages; deliberately narrower, and marked `local_fallback` in state so it's never confused with model output | Active |

What's **not** here, on purpose: no ColBERT, no LayoutLMv3, no Neo4j, no hidden multi-agent theater. Every one of those would either be unverifiable in a hackathon timeline or add failure surface with zero judge-visible benefit. Honest scope beats decorative scope.

---

## Quickstart

**Backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # add GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000
```

**Frontend** (new terminal)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

**Windows, one command:**

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
```

**Docker (backend only):**

```bash
docker build -t samvida-backend ./backend
docker run -p 8000:8000 --env-file backend/.env samvida-backend
```

No `GEMINI_API_KEY`? Set `CONTRACTLENS_OFFLINE=1` — the deterministic local extractor keeps the full pause/resume/timeline pipeline running end to end.

---

## It's actually tested

```bash
cd backend
pip install -r requirements-dev.txt
pytest -v
```

Six tests assert real outcomes against the real demo contract — not "the server returned 200":

```python
def test_payment_quote_grounds_to_section_3_2(doc):
    ...
    assert ev["section_number"] == "3.2"          # not "1" -- the bug that used to exist

def test_verification_catches_number_conflict(doc):
    ...
    assert out["verification_status"] == CONFLICTING_EVIDENCE   # catches a wrong claim

def test_local_demo_timeline_separates_time_and_decision(doc, monkeypatch):
    ...
    assert payment["basis"] == "75 days after invoice date"     # never a fabricated date
    assert fee["fee"] == "USD 45,000"                            # the fee is never dropped

def test_knowledge_graph_and_cross_clause_edges(doc):
    ...
    assert "SURVIVES_TERMINATION" in relations
```

A separate grounding smoke test (`backend/test_grounding_smoke.py`) checks 3/3 known clauses resolve to their exact section number and title before any demo recording.

---

## Evidence model

**Tier 1** — verbatim quote -> PyMuPDF word-level rectangles -> visual PDF highlight.
**Tier 2** — when spatial mapping can't be proven, page + section + exact excerpt. Never a dead end, never a fabricated coordinate.

Every material finding also carries its verification status, so "sounds right" and "checked against its own source" are never the same badge.

---

## Demo contract — ground truth

`Veritas_Cloud_Master_Services_Agreement.pdf` — a clean, digital, single-column 5-page B2B SaaS agreement, chosen specifically so exact-span highlighting is provable, not approximate.

| Clause | What it hides |
|---|---|
| §2.2 | Perpetual automatic renewal, 90-day non-renewal notice |
| §3.2 | 75-day undisputed-invoice payment term |
| §3.4 | Renewal price increases capped at 9%, 30-day notice |
| §4.3 | 30-day service-credit claim window |
| §6.1 | Annual SOC 2 Type II report due no later than 30 June |
| §9.1 | 60-day termination-for-convenience notice, USD 45,000 exit fee, plus accrued fees |

For a repeatable demo recording where "today" always lands after the June 30 deadline:

```bash
export CONTRACTLENS_TODAY=2026-09-20
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Model + key status |
| `POST` | `/api/contracts` | Upload -> parse -> run to first interrupt |
| `GET` | `/api/runs/{doc_id}` | Current agent state, findings, timeline, insights, graph edges, audit |
| `POST` | `/api/runs/{doc_id}/decision` | Record `confirm` / `dismiss` / `route`, resume the graph |
| `POST` | `/api/contracts/{doc_id}/ask` | Grounded natural-language question over the contract |

---

## Scope, honestly stated

- Digital, text-based B2B PDF contracts. No OCR — scans and photographs are out of scope on purpose.
- Session state lives in LangGraph's `MemorySaver` and an in-memory doc store; restarting the backend clears it. No database, no accounts, no auth — this is a hackathon vertical slice, not a production tenant system.
- SAMVIDA reduces the manual effort of reading and tracking business contracts. It does not replace legal judgment, does not claim zero hallucinations, and does not offer legal advice.

---

<div align="center">

**#AIHackathon #BuildWithAI #ProductSpace**

</div>