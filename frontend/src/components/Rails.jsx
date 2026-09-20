import { useRef } from "react";
const KIND_LABEL = { ACTION: "Action", MILESTONE: "Milestone", CONDITION: "Condition", RELATIVE_DEADLINE: "Relative deadline", ALERT: "Alert" };
const STATUS_LABEL = { OVERDUE: "Overdue", DUE_SOON: "Due soon", UPCOMING: "Upcoming", TRACKED: "Tracked", RELATIVE: "Relative" };
const DECISION_LABEL = { PENDING: "Pending review", CONFIRMED: "Confirmed", "ROUTED FOR REVIEW": "Routed for review" };

function statusClass(status) { return "status-" + String(status || "tracked").toLowerCase().replace(/\s+/g, "-"); }
function whenText(t) {
  if (t.temporal_status === "OVERDUE") return `Was due ${t.date}`;
  if (t.date) return t.date;
  if (t.basis) return `Timing: ${t.basis}`;
  return "Timing not yet triggered";
}

export function Timeline({ items, onOpen }) {
  const railRef = useRef(null);
  const overdue = items.filter((t) => t.temporal_status === "OVERDUE").length;

  function scrollRail(amount) {
    railRef.current?.scrollBy({ left: amount, behavior: "smooth" });
  }

  function handleRailWheel(e) {
    // A normal mouse-wheel gesture is vertical; convert it to horizontal
    // movement while the pointer is over the timeline so all 11+ items are
    // reachable without requiring a trackpad or Shift+wheel.
    const rail = railRef.current;
    if (!rail || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    const max = rail.scrollWidth - rail.clientWidth;
    if (max <= 0) return;
    e.preventDefault();
    rail.scrollLeft = Math.max(0, Math.min(max, rail.scrollLeft + e.deltaY));
  }

  function handleRailKeyDown(e) {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      scrollRail(340);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      scrollRail(-340);
    } else if (e.key === "Home") {
      e.preventDefault();
      railRef.current?.scrollTo({ left: 0, behavior: "smooth" });
    } else if (e.key === "End") {
      e.preventDefault();
      const rail = railRef.current;
      rail?.scrollTo({ left: rail.scrollWidth, behavior: "smooth" });
    }
  }

  return (
    <footer className="rail-wrap">
      <div className="railhead">
        <div>
          <h3>Action timeline</h3>
          <span className="count">{items.length} {items.length === 1 ? "item" : "items"}{overdue > 0 && <span className="overdue-flag"> · {overdue} overdue</span>}</span>
        </div>
        {items.length > 0 && (
          <div className="rail-controls" aria-label="Timeline navigation">
            <span className="rail-hint">Scroll to explore</span>
            <button className="rail-nav" type="button" aria-label="Scroll timeline left" onClick={() => scrollRail(-340)}>←</button>
            <button className="rail-nav" type="button" aria-label="Scroll timeline right" onClick={() => scrollRail(340)}>→</button>
          </div>
        )}
      </div>
      <div
        className="rail"
        ref={railRef}
        tabIndex={0}
        aria-label="Contract action timeline"
        onWheel={handleRailWheel}
        onKeyDown={handleRailKeyDown}
      >
        {items.length === 0 && <p className="rail-empty">Confirmed and tracked findings appear here, separated from plain contract facts.</p>}
        {items.map((t) => (
          <button key={t.id} className={`tlitem ${statusClass(t.temporal_status)}`} onClick={() => onOpen(t.id)}>
            <div className="tl-top">
              <span className="tl-kind">{KIND_LABEL[t.kind] || t.kind}</span>
              <span className={`tl-status ${statusClass(t.temporal_status)}`}>{STATUS_LABEL[t.temporal_status] || t.temporal_status}</span>
            </div>
            <div className="tl-title">{t.title}</div>
            <div className="tl-when">{whenText(t)}</div>
            {t.meaning && <p className="tl-meaning">{t.meaning}</p>}
            {t.fee && <div className="tl-fee">Fee: {t.fee}</div>}
            {t.consequence && <p className="tl-consequence">{t.consequence}</p>}
            {t.decision_status && t.decision_status !== "PENDING" && (
              <div className={`tl-decision decision-${statusClass(t.decision_status)}`}>{DECISION_LABEL[t.decision_status] || t.decision_status}</div>
            )}
            <div className="tl-foot">
              {t.party && <span>{t.party}</span>}
              {t.section && <span>{t.section}</span>}
              {!t.section && t.page && <span>page {t.page}</span>}
            </div>
            {t.mergedLabels?.length > 0 && <div className="tl-merged">Also covers: {t.mergedLabels.join(", ")}</div>}
          </button>
        ))}
      </div>
    </footer>
  );
}

export function AuditTrail({ events }) {
  if (!events.length) return <p className="rail-empty">No events recorded yet.</p>;
  return <div className="audit">{events.map((e, i) => <div className="auditrow" key={i}><time>{new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time><span><strong>{e.what}</strong>{e.detail ? ` — ${e.detail}` : ""}</span></div>)}</div>;
}
