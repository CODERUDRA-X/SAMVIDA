const CATEGORY = {
  term: "term",
  renewal: "renewal",
  payment: "payment",
  termination: "termination",
  "service-level": "service level",
  obligation: "obligation",
  data: "data",
  liability: "liability"
};

function evidenceLabel(ev = {}) {
  if (ev.tier === 1) {
    return ev.section ? `Exact passage · ${ev.section} · p.${ev.page}` : `Exact passage · p.${ev.page}`;
  }
  if (ev.page) return ev.section ? `${ev.section} · p.${ev.page}` : `Page ${ev.page} reference`;
  return "Source excerpt";
}

function decisionNote(choice) {
  return {
    confirm: "Confirmed by you — carried into the action timeline.",
    dismiss: "Dismissed by you — kept out of the action timeline.",
    route: "Routed for human review — tracked, not actioned."
  }[choice];
}

export function FindingCard({ finding, onViewSource }) {
  const ev = finding.evidence || {};
  const risky = finding.risk === "high";
  return (
    <article className={`card ${risky ? "risk" : "finding"}`}>
      <div className="k">{CATEGORY[finding.category] || finding.category}</div>
      <h4>{finding.label}</h4>
      <p>{finding.summary}</p>
      {finding.quote && <blockquote>{finding.quote}</blockquote>}
      <div className="meta">
        <span className={`chip ${ev.tier === 1 ? "t1" : "t2"}`}>{evidenceLabel(ev)}</span>
        {finding.party && <span className="chip">{finding.party}</span>}
        <button className="src" onClick={() => onViewSource(finding)}>View source</button>
      </div>
      {finding.decision && <div className="decided">{decisionNote(finding.decision)}</div>}
    </article>
  );
}

export function InterventionCard({ finding, onDecide, busy, onViewSource }) {
  const ev = finding.evidence || {};
  return (
    <article className="card halt">
      <div className="k">execution paused</div>
      <h4>{finding.label}</h4>
      <p>{finding.summary}</p>
      {finding.quote && <blockquote>{finding.quote}</blockquote>}
      <div className="meta">
        <span className={`chip ${ev.tier === 1 ? "t1" : "t2"}`}>{evidenceLabel(ev)}</span>
        <button className="src" onClick={() => onViewSource(finding)}>View source</button>
      </div>
      <p className="why">
        <strong>Why the agent stopped:</strong> {finding.why}
      </p>
      {finding.rules?.length > 0 && (
        <div className="meta">
          {finding.rules.map((r) => (
            <span key={r.id} className="chip rule">{r.id} · {r.label}</span>
          ))}
        </div>
      )}
      <div className="actions">
        <button className="act primary" disabled={busy} onClick={() => onDecide(finding.id, "confirm")}>
          Confirm finding
        </button>
        <button className="act" disabled={busy} onClick={() => onDecide(finding.id, "dismiss")}>
          Dismiss
        </button>
        <button className="act route" disabled={busy} onClick={() => onDecide(finding.id, "route")}>
          Route for human review
        </button>
      </div>
      {busy && <div className="decided">Resuming the agent workflow…</div>}
    </article>
  );
}

export function SystemCard({ children }) {
  return <article className="card sys"><p>{children}</p></article>;
}

export function ErrorCard({ children, onRetry }) {
  return (
    <article className="card err">
      <div className="k">the agent could not continue</div>
      <p>{children}</p>
      {onRetry && <div className="actions"><button className="act" onClick={onRetry}>Try again</button></div>}
    </article>
  );
}
