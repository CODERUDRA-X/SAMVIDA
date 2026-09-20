export function Timeline({ items, onOpen }) {
  return (
    <footer className="rail-wrap">
      <div className="railhead">
        <h3>Action timeline</h3>
        <span className="count">
          {items.length} {items.length === 1 ? "tracked action" : "tracked actions"}
        </span>
      </div>
      <div className="rail">
        {items.length === 0 && (
          <p className="rail-empty">Confirmed findings become tracked actions here.</p>
        )}
        {items.map((t) => (
          <button key={t.id} className={`tlitem ${t.status === "ROUTED FOR REVIEW" ? "routed" : ""}`} onClick={() => onOpen(t.id)}>
            <span className="dte">{t.date || t.basis || "Timing to confirm"}</span>
            <span className="obl">{t.label}</span>
            <span className="who">
              {[t.party, t.section || (t.page ? `page ${t.page}` : ""), t.status].filter(Boolean).join(" · ")}
            </span>
          </button>
        ))}
      </div>
    </footer>
  );
}

export function AuditTrail({ events }) {
  if (!events.length) return <p className="rail-empty">No events recorded yet.</p>;
  return (
    <div className="audit">
      {events.map((e, i) => (
        <div className="auditrow" key={i}>
          <time>{new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
          <span>
            <strong>{e.what}</strong>
            {e.detail ? ` — ${e.detail}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}
