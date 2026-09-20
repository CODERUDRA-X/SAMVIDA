# SAMVIDA — Contract-to-Action Intelligence Agent

**SAMVIDA** turns a business contract from a static document into a source-verifiable action workspace.

It parses digital B2B PDF contracts, extracts commercial terms and operational obligations, maps findings back to source text, runs deterministic review policies, checks extracted claims against the source again, and **pauses its stateful agent workflow** when a high-review condition needs human direction.

Built for Problem Statement 4 of the Product Space Agentic AI Hackathon 2026. It is decision support, not legal advice, and findings are not guaranteed correct.

## Run

Python 3.11–3.14 and Node 22.12+ are supported. The development model is selected with `CONTRACTLENS_MODEL` (default: `gemini-3.5-flash-lite`). For final demo validation, set a stronger model you have access to.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# add GEMINI_API_KEY=...
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Agent loop

```text
PDF → Parse → Extract → Evaluate → Ground → Verify → Checkpoint
                                      ↓               ↓
                              clause graph        [INTERRUPT]
                                      ↓               ↓
                              cross-clause      human decision
                                      └──────→ Resume → Plan
```

The graph uses an explicit LangGraph checkpoint. A high-review finding becomes `pending_id`; the workflow is interrupted before the human-intervention node. The decision endpoint writes `confirm`, `dismiss`, or `route` into graph state and resumes the same thread.

## Evidence model

**Tier 1:** verbatim quote mapped to PyMuPDF word-level rectangles for visual highlighting.

**Tier 2:** when coordinates cannot be proven, return page/section/excerpt only. No fake bounding boxes are generated.

Every material finding also receives deterministic verification checks for source location and claim atoms such as numbers, money and explicit dates.

## Research-grade upgrades in this build

- Layout-aware `Document` / clause hierarchy with stable section numbers.
- Parent-child style retrieval: sentence-sized search units retain their parent clause context.
- Lightweight clause knowledge graph with explicitly supported relations such as `REQUIRES_NOTICE`, `HAS_DEADLINE`, `CONDITIONAL_ON`, `DEPENDS_ON`, `TRIGGERS`, `SURVIVES_TERMINATION`, and `INDEMNIFIES`.
- Bounded cross-clause analysis that labels outputs as `POTENTIAL_INTERACTION` rather than legal conclusions.
- Chain-of-verification checks that expose verification results, not hidden model reasoning.
- Deterministic risk policy separated from model extraction.
- Timeline semantics separated into `kind`, temporal status (`OVERDUE`, `DUE_SOON`, `UPCOMING`, `RELATIVE`, `TRACKED`) and human decision status (`CONFIRMED`, `ROUTED FOR REVIEW`, `PENDING`). A confirmation never erases an overdue state.
- Deterministic local fallback for offline testing and API outage recovery; it is intentionally narrower than the Gemini path and marked `local_fallback` in state.

## Demo contract

`Veritas_Cloud_Master_Services_Agreement.pdf` is a clean digital 5-page contract containing, among other terms:

- perpetual automatic renewal with 90-day non-renewal notice;
- 75-day undisputed invoice payment terms;
- renewal-term price increases capped at 9%;
- an annual SOC 2 Type II report due no later than 30 June;
- a 60-day convenience-termination notice with a USD 45,000 early termination fee plus accrued fees.

For a repeatable recording, set `CONTRACTLENS_TODAY=2026-09-20`.

## Scope / limits

- Digital text-based B2B PDFs only. No OCR for scans/photographs.
- Session state uses LangGraph `MemorySaver` and an in-memory document store; restart the backend to clear the session.
- No authentication, accounts or database in the hackathon build.


## Windows setup

For a clean Windows setup, run `powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1`. The script creates the backend virtual environment, installs the Python dependencies, and installs the frontend dependencies.

The backend requirements use a Pydantic release with CPython 3.14 support. The frontend uses current Vite/React tooling and a current PDF.js release; PDF scripting is disabled in the viewer because uploaded documents are untrusted input.


## Product experience

On first load, SAMVIDA opens with a short premium identity sequence and then enters the workspace. Selecting a document immediately shows a real processing state while the backend works, even when the response returns in under a second. After a human checkpoint, the UI shows a brief resume state before the updated graph state arrives. The completed workspace separates the autonomous feed, source evidence, contract investigation, action timeline and audit trail.

## Deployment configuration

The frontend reads `VITE_API_BASE` at build time. Keep it as `/api` for local Vite proxy development; for a separately hosted backend, set it to the public backend API base URL. The backend uses `CONTRACTLENS_ORIGINS` for production CORS configuration. No API key is bundled into the frontend.
