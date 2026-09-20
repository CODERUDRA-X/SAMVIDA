import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.js?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * Renders the contract and draws the evidence rectangles the backend produced.
 * Rects arrive in PDF point space; PyMuPDF and pdf.js share a top-left origin,
 * so a single scale factor maps them onto the rendered canvas.
 */
export default function PdfPane({ file, highlight, onReady }) {
  const hostRef = useRef(null);
  const pageRefs = useRef([]);
  const [scale, setScale] = useState(1);
  const [status, setStatus] = useState("idle");

  useEffect(() => {
    if (!file) return;
    let cancelled = false;

    (async () => {
      setStatus("rendering");
      const host = hostRef.current;
      host.innerHTML = "";
      pageRefs.current = [];

      try {
        const buf = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
        const width = Math.min(760, Math.max(360, host.clientWidth - 72));

        for (let n = 1; n <= pdf.numPages; n++) {
          if (cancelled) return;
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
        if (!cancelled) {
          setStatus("ready");
          onReady?.(pdf.numPages);
        }
      } catch (err) {
        if (!cancelled) setStatus("failed");
      }
    })();

    return () => { cancelled = true; };
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
