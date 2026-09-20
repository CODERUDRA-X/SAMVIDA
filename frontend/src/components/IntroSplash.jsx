import { useEffect, useRef, useState } from "react";

const INTRO_HOLD_MS = 4300;
const INTRO_EXIT_MS = 720;

export default function IntroSplash({ onDone }) {
  const [leaving, setLeaving] = useState(false);
  const doneRef = useRef(false);
  const exitTimerRef = useRef(null);

  function finish() {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    exitTimerRef.current = window.setTimeout(onDone, INTRO_EXIT_MS);
  }

  useEffect(() => {
    const timer = window.setTimeout(finish, INTRO_HOLD_MS);
    return () => {
      window.clearTimeout(timer);
      if (exitTimerRef.current) window.clearTimeout(exitTimerRef.current);
    };
  }, [onDone]);

  return (
    <div className={`intro ${leaving ? "intro-leave" : ""}`} role="dialog" aria-label="SAMVIDA introduction" aria-modal="true">
      <div className="intro-noise" aria-hidden="true" />
      <div className="intro-grid" aria-hidden="true" />
      <div className="intro-vignette" aria-hidden="true" />

      <div className="intro-center">
        <div className="intro-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>

        <div className="intro-wordmark" aria-label="SAMVIDA">
          S<span className="brand-glyph">Λ</span>MVID<span className="brand-glyph">Λ</span>
        </div>
        <div className="intro-line" aria-hidden="true" />
        <div className="intro-kicker">CONTRACT · EVIDENCE · CONTROL</div>
        <div className="intro-sub">Contract-to-Action Intelligence Agent</div>

        <div className="intro-seal">
          <span className="intro-seal-line" />
          <span>CONTROLLED AUTONOMY</span>
          <span className="intro-seal-line" />
        </div>
      </div>

      <div className="intro-footer">
        <span>Verifiable intelligence for business contracts</span>
        <button className="intro-skip" type="button" onClick={finish} disabled={leaving}>
          Skip intro <span aria-hidden="true">↗</span>
        </button>
      </div>

      <div className="intro-progress" aria-hidden="true">
        <span />
      </div>
    </div>
  );
}
