import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PdfPane from "./components/PdfPane.jsx";
import { ErrorCard, FindingCard, InterventionCard, SystemCard } from "./components/AgentFeed.jsx";
import { AuditTrail, Timeline } from "./components/Rails.jsx";
import { api } from "./lib/api.js";

const STEPS = ["Parse", "Extract", "Evaluate", "Ground", "Checkpoint", "Resume", "Plan"];

const STAGE_META = {
  IDLE: { step: -1, tone: "idle", label: "Idle" },
  PARSED: { step: 0, tone: "run", label: "Parsing" },
  EXTRACTED: { step: 1, tone: "run", label: "Extracting" },
  EVALUATED: { step: 2, tone: "run", label: "Evaluating risk" },
  GROUNDED: { step: 3, tone: "run", label: "Grounding evidence" },
  CHECKPOINT_CLEAR: { step: 4, tone: "run", label: "Checkpoint clear" },
  AWAITING_HUMAN_REVIEW: { step: 4, tone: "halt", label: "Paused — human verification required" },
  RESUMING: { step: 5, tone: "run", label: "Resuming" },
  COMPLETED: { step: 6, tone: "done", label: "Completed" },
  ERROR: { step: -1, tone: "err", label: "Stopped on an error" }
};

export default function App() {
  const [file, setFile] = useState(null);
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [fatal, setFatal] = useState("");
  const [highlight, setHighlight] = useState(null);
  const [view, setView] = useState("feed");
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState([]);
  const [asking, setAsking] = useState(false);
  const inputRef = useRef(null);

  const meta = STAGE_META[run?.stage] || STAGE_META.IDLE;
  const findings = run?.findings || [];
  const pending = useMemo(
    () => findings.find((f) => f.id === run?.pendingId && !f.decision),
    [findings, run]
  );
  const visible = useMemo(
    () => findings.filter((f) => f.id !== run?.pendingId || f.decision),
    [findings, run]
  );

  const viewSource = useCallback((f) => {
    const ev = f.evidence;
    if (!ev) return;
    setHighlight({ page: ev.page, rects: ev.rects, tier: ev.tier, key: Math.random() });
  }, []);

  async function handleFile(f) {
    if (!f) return;
    setFatal("");
    setAnswers([]);
    setHighlight(null);
    setFile(f);
    setBusy(true);
    try {
      setRun(await api.upload(f));
    } catch (e) {
      setFatal(e.message);
      setRun(null);
    } finally {
      setBusy(false);
    }
  }

  async function decide(findingId, choice) {
    setBusy(true);
    try {
      setRun(await api.decide(run.docId, findingId, choice));
    } catch (e) {
      setFatal(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function ask(e) {
    e.preventDefault();
    const q = question.trim();
    if (!q || !run) return;
    setQuestion("");
    setAsking(true);
    setAnswers((a) => [...a, { q, pendingAnswer: true }]);
    try {
      const r = await api.ask(run.docId, q);
      setAnswers((a) => [...a.slice(0, -1), { q, ...r }]);
    } catch (err) {
      setAnswers((a) => [...a.slice(0, -1), { q, error: err.message }]);
    } finally {
      setAsking(false);
    }
  }

  // move the highlight automatically when the agent halts, so the evidence is
  // already on screen when the reviewer reads the intervention card
  useEffect(() => {
    if (pending?.evidence) viewSource(pending);
  }, [pending, viewSource]);

  function openTimelineItem(id) {
    const f = findings.find((x) => x.id === id);
    if (f) viewSource(f);
  }

  return (
    <div className="app">
      <header>
        <div className="brand">
          <b>ContractLens</b>
          <span>Contract-to-Action Intelligence Agent</span>
        </div>
        <div className="docname">{run?.fileName || file?.name || "No contract loaded"}</div>
        <div className={`statepill ${meta.tone}`}>
          <i className="dot" />
          {meta.label}
        </div>
      </header>

      <main>
        {file ? (
          <PdfPane file={file} highlight={highlight} />
        ) : (
          <section className="docpane">
            <div className="pane-msg">
              <h3>Load a business contract</h3>
              <p>The agent reads the document on its own. No prompt is required to start.</p>
              <button className="btn" onClick={() => inputRef.current.click()} disabled={busy}>
                {busy ? "Parsing…" : "Choose PDF"}
              </button>
              <p className="scopenote">
                Scope: text-based digital B2B agreements — vendor, SaaS, service and partnership
                contracts. Scanned or photographed documents are out of scope.
              </p>
            </div>
          </section>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => handleFile(e.target.files?.[0])}
        />

        <section className="agentpane">
          <div className="stepper">
            {STEPS.map((s, i) => (
              <div key={s} className={`step ${i < meta.step ? "on" : i === meta.step ? "cur" : ""}`}>
                <i />
                {s}
              </div>
            ))}
          </div>

          <div className="paneheader">
            <h3>{view === "feed" ? "Agent action feed" : "Audit trail"}</h3>
            <div className="tabs">
              <button className={view === "feed" ? "tab on" : "tab"} onClick={() => setView("feed")}>Feed</button>
              <button className={view === "audit" ? "tab on" : "tab"} onClick={() => setView("audit")}>
                Audit trail
              </button>
            </div>
          </div>

          <div className="feed">
            {view === "audit" ? (
              <AuditTrail events={run?.audit || []} />
            ) : (
              <>
                {!run && !fatal && (
                  <p className="rail-empty">Upload a contract to start the agent.</p>
                )}
                {fatal && <ErrorCard>{fatal}</ErrorCard>}
                {run?.error && <ErrorCard>{run.error}</ErrorCard>}

                {run?.parties?.customer && (
                  <SystemCard>
                    {[
                      run.parties.customer && `Customer: ${run.parties.customer}`,
                      run.parties.supplier && `Supplier: ${run.parties.supplier}`,
                      run.effectiveDate && `Effective ${run.effectiveDate}`,
                      run.expirationDate && `Expires ${run.expirationDate}`
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </SystemCard>
                )}

                {visible.map((f) => (
                  <FindingCard key={f.id} finding={f} onViewSource={viewSource} />
                ))}

                {pending && (
                  <InterventionCard
                    finding={pending}
                    onDecide={decide}
                    onViewSource={viewSource}
                    busy={busy}
                  />
                )}

                {answers.map((a, i) => (
                  <article className="card qa" key={i}>
                    <div className="k">question</div>
                    <p className="qtext">{a.q}</p>
                    {a.pendingAnswer && <p className="dim">Reading the contract…</p>}
                    {a.error && <p className="dim">{a.error}</p>}
                    {a.answer && <p>{a.answer}</p>}
                    {a.quote && (
                      <>
                        <blockquote>{a.quote}</blockquote>
                        <button className="src" onClick={() => viewSource(a)}>View source</button>
                      </>
                    )}
                  </article>
                ))}
              </>
            )}
          </div>

          <form className="askbar" onSubmit={ask}>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about this contract…"
              disabled={!run || asking}
            />
            <button className="btn ghost" disabled={!run || asking || !question.trim()}>
              {asking ? "Asking…" : "Ask"}
            </button>
          </form>
        </section>
      </main>

      <Timeline items={run?.timeline || []} onOpen={openTimelineItem} />
    </div>
  );
}
