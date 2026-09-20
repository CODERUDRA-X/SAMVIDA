export default function ProcessingCard({ mode = "upload" }) {
  const resume = mode === "resume";
  return (
    <article className="processing-card" aria-live="polite">
      <div className="processing-topline">
        <span className="processing-dot" />
        <span>{resume ? "Agent resuming" : "Agent processing"}</span>
      </div>
      <h4>{resume ? "Updating the contract action plan" : "Reading the contract autonomously"}</h4>
      <p>
        {resume
          ? "Rechecking the workflow after your decision and rebuilding the tracked actions."
          : "Parsing clauses, extracting obligations, evaluating risk, and attaching source evidence."}
      </p>
      <div className="skeleton-stack" aria-hidden="true">
        <span className="sk sk-wide" />
        <span className="sk sk-mid" />
        <span className="sk sk-short" />
      </div>
      <div className="processing-meta">
        {resume ? "State checkpoint accepted" : "No prompt required"}
        <span>•</span>
        {resume ? "Timeline recalculating" : "Source grounding active"}
      </div>
    </article>
  );
}
