import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * Renders the contract and draws the evidence rectangles the backend produced.
 * Rects arrive in PDF point space; PyMuPDF and pdf.js share a top-left origin,
 * so a single scale factor maps them onto the rendered canvas.
 */
export default function PdfPane({ file, highlight, onReady }) {
  const paneRef = useRef(null);
  const hostRef = useRef(null);
  const pageRefs = useRef([]);
  const [scale, setScale] = useState(1);
  const [status, setStatus] = useState("idle");

  useEffect(() => {
    if (!file) return;

    let cancelled = false;
    let renderSerial = 0;
    let resizeTimer = 0;
    let lastRenderWidth = 0;
    const pane = paneRef.current;
    const host = hostRef.current;

    async function renderDocument() {
      if (!host || !pane || cancelled) return;

      const availableWidth = Math.max(1, host.clientWidth - 48);
      const width = Math.min(760, availableWidth);
      if (Math.abs(width - lastRenderWidth) < 1) return;
      lastRenderWidth = width;

      const serial = ++renderSerial;
      const previousScrollTop = pane.scrollTop;
      setStatus("rendering");
      host.innerHTML = "";
      pageRefs.current = [];

      try {
        const buf = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: buf, enableScripting: false }).promise;

        for (let n = 1; n <= pdf.numPages; n++) {
          if (cancelled || serial !== renderSerial) return;
          const page = await pdf.getPage(n);
          const base = page.getViewport({ scale: 1 });
          const s = width / base.width;
          if (n === 1) setScale(s);
          const vp = page.getViewport({ scale: s });

          const holder = document.createElement("div");
          holder.className = "page";
          holder.style.width = `${vp.width}px`;
          holder.style.height = `${vp.height}px`;

          const canvas = document.createElement("canvas");
          const ratio = Math.min(2, window.devicePixelRatio || 1);
          canvas.width = Math.floor(vp.width * ratio);
          canvas.height = Math.floor(vp.height * ratio);
          canvas.style.width = `${vp.width}px`;
          canvas.style.height = `${vp.height}px`;
          holder.appendChild(canvas);

          const overlay = document.createElement("div");
          overlay.className = "overlay";
          holder.appendChild(overlay);

          const tag = document.createElement("div");
          tag.className = "pageno";
          tag.textContent = `p. ${n}`;
          holder.appendChild(tag);

          host.appendChild(holder);
          pageRefs.current[n] = { holder, overlay, scale: s };

          await page.render({
            canvasContext: canvas.getContext("2d"),
            viewport: vp,
            transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null
          }).promise;
        }

        if (!cancelled && serial === renderSerial) {
          pane.scrollTop = Math.min(previousScrollTop, Math.max(0, pane.scrollHeight - pane.clientHeight));
          setStatus("ready");
          onReady?.(pdf.numPages);
        }
      } catch (err) {
        if (!cancelled && serial === renderSerial) setStatus("failed");
      }
    }

    renderDocument();

    const observer = new ResizeObserver(() => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        renderDocument();
      }, 120);
    });
    observer.observe(pane);

    return () => {
      cancelled = true;
      renderSerial += 1;
      window.clearTimeout(resizeTimer);
      observer.disconnect();
    };
  }, [file, onReady]);

  // draw / move the evidence highlight
  useEffect(() => {
    pageRefs.current.forEach((p) => p && (p.overlay.innerHTML = ""));
    if (!highlight) return;
    const { page, rects, tier } = highlight;
    const target = pageRefs.current[page];
    if (!target) return;

    if (tier === 1 && rects?.length) {
      rects.forEach(([x0, y0, x1, y1]) => {
        const box = document.createElement("div");
        box.className = "hl";
        box.style.left = `${x0 * target.scale}px`;
        box.style.top = `${y0 * target.scale}px`;
        box.style.width = `${(x1 - x0) * target.scale}px`;
        box.style.height = `${(y1 - y0) * target.scale}px`;
        target.overlay.appendChild(box);
      });
      const first = target.overlay.firstChild;
      first?.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      target.holder.classList.add("page-flash");
      target.holder.scrollIntoView({ behavior: "smooth", block: "start" });
      setTimeout(() => target.holder.classList.remove("page-flash"), 1600);
    }
  }, [highlight, scale]);

  return (
    <section className="docpane">
      <div className="docinner" ref={hostRef} />
      {status === "failed" && (
        <div className="pane-msg">
          <h3>That PDF could not be rendered</h3>
          <p>ContractLens reads text-based digital contracts. Scans and photographs are out of scope.</p>
        </div>
      )}
    </section>
  );
}
