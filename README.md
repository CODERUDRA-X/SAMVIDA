# ContractLens — Contract-to-Action Intelligence Agent

Turns a business contract from a static document into a verifiable action plan.

The agent parses a contract, extracts commercial terms and deadline-bound obligations, grounds
every finding back to the source passage, applies a deterministic risk rule set, and **halts its
own execution** when a high-risk condition is detected — resuming only after a human gives it
direction.

Built for Problem Statement 4 of the Product Space Agentic AI Hackathon 2026.
It reduces the manual effort of understanding and tracking business contracts. It does not
replace legal professionals, and it is not a substitute for legal advice.

---

## Run it

Two terminals. Python 3.11+ and Node 18+.

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# get a free key (no card needed): https://aistudio.google.com/apikey
# paste it into .env as GEMINI_API_KEY=...
uvicorn app.main:app --reload --port 8000
```

Check it came up: <http://127.0.0.1:8000/api/health> should report `"keyPresent": true`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to the backend, so there is no CORS setup to do.

---

## The demo path

Use `Veritas_Cloud_Master_Services_Agreement.pdf`. It is a clean digital PDF containing
perpetual automatic renewal, a 90-day non-renewal notice, a 75-day payment term, a 9% annual
price adjustment, a 60-day termination notice and a USD 45,000 early termination fee.

1. **Choose PDF** — no prompt is typed. The agent starts on its own.
2. The action feed fills with grounded findings. Each carries a verbatim quote and a source chip.
3. **View source** — the exact passage is boxed on the page to the left.
4. The agent stops. The status pill turns amber: *Paused — human verification required*.
   The intervention card names the rule that fired and why it matters.
5. **Confirm finding** — the graph resumes from its checkpoint.
6. The action timeline fills. The audit trail tab shows the whole run, including your decision.

---

## Architecture

```
React (Vite) ──HTTP──> FastAPI ──> LangGraph state machine ──> Gemini API (free tier)
     │                                      │
  pdfjs-dist                            PyMuPDF
  canvas + bbox overlay              word-level boxes
```

### The state machine

```
parse → extract_obligations → evaluate_risk → ground_evidence → checkpoint
checkpoint ──(high-risk pending)──> [INTERRUPT] human_intervention → checkpoint
checkpoint ──(nothing pending)────> finalize → END
```

The pause is enforced by the graph, not by the interface. The graph is compiled with
`interrupt_before=["human_intervention"]` and a `MemorySaver` checkpointer keyed by document id.
When it halts, execution genuinely stops inside the checkpointer; `GET /api/runs/{id}` reports
`interrupted: true` and `nextNodes: ["human_intervention"]`. The run continues only when
`POST /api/runs/{id}/decision` writes the decision into state and re-invokes the graph.

### Why risk is not a model judgement

The model extracts and quotes. Five deterministic rules in `backend/app/risk.py` decide whether
the agent halts:

| Rule | Condition | Severity |
|---|---|---|
| R1-AUTO-RENEWAL | automatic, perpetual or successive renewal | high |
| R2-PAYMENT-TERM | payment window longer than 60 days | high |
| R3-EXIT-FEE | early termination fee | high |
| R4-NOTICE-WINDOW | notice period of 60 days or more | medium |
| R5-PRICE-ESCALATION | contractual price escalation right | medium |

So "why did the agent stop?" always has an explicit, inspectable, reproducible answer.

### Two-tier evidence

Tier 1 maps a verbatim quote onto word-level bounding boxes from PyMuPDF and draws them over the
rendered page. Tier 2 falls back to section, page and the source excerpt when exact mapping
fails. Every finding carries one or the other, and the interface labels which. Exact highlighting
is never a single point of failure.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | model and key status |
| POST | `/api/contracts` | upload, parse, run to the first interrupt |
| GET | `/api/runs/{doc_id}` | current agent state |
| POST | `/api/runs/{doc_id}/decision` | record a decision, resume the graph |
| POST | `/api/contracts/{doc_id}/ask` | grounded natural-language question |

---

## Scope and limits

- Text-based digital B2B contracts: vendor, SaaS, service, SLA and partnership agreements.
- Scanned or photographed documents are out of scope; there is no OCR.
- State is held in memory for the session; there is no database, no accounts and no auth.
- Findings are source-grounded and human-verified, not guaranteed correct. Every material
  finding exposes the passage it came from so a person can check it.
