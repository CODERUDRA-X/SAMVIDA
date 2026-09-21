import { useEffect, useRef, useState } from "react";

import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * Renders the contract and draws the evidence rectangles the backend produced.
 *
 * The PDF is rendered into a detached staging container first and swapped into
 * the visible pane only after all pages are ready. Resize handling listens to
 * the browser window rather than the scrollable PDF pane, avoiding a resize
 * feedback loop caused by the pane's own vertical scrollbar.
 */
export default function PdfPane({ file, highlight, onReady }) {
  const paneRef = useRef(null);
  const hostRef = useRef(null);
  const pageRefs = useRef([]);
  const onReadyRef = useRef(onReady);

  const [scale, setScale] = useState(1);
  const [status, setStatus] = useState("idle");

  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  useEffect(() => {
    if (!file) return;

    let cancelled = false;
    let renderSerial = 0;
    let resizeTimer = 0;
    let lastRenderWidth = 0;

    const pane = paneRef.current;
    const host = hostRef.current;

    async function renderDocument(force = false) {
      if (!host || !pane || cancelled) return;

      // The pane itself is scrollable. Use its client width so the scrollbar
      // does not create a width/resize feedback loop.
      const availableWidth = Math.max(1, pane.clientWidth - 48);
      const width = Math.min(760, availableWidth);

      if (!force && Math.abs(width - lastRenderWidth) < 1) return;
      lastRenderWidth = width;

      const serial = ++renderSerial;
      const previousScrollTop = pane.scrollTop;

      setStatus("rendering");

      // Render into a detached staging host. The current document stays visible
      // until the new document has finished rendering, so there is no blank flash.
      const staging = document.createElement("div");
      staging.className = "docinner";
      staging.style.width = "100%";

      const nextPageRefs = [];

      try {
        const buf = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({
          data: buf,
          enableScripting: false
        }).promise;

        for (let n = 1; n <= pdf.numPages; n++) {
          if (cancelled || serial !== renderSerial) return;

          const page = await pdf.getPage(n);
          const base = page.getViewport({ scale: 1 });
          const s = width / base.width;
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

          staging.appendChild(holder);
          nextPageRefs[n] = { holder, overlay, scale: s };

          await page.render({
            canvasContext: canvas.getContext("2d"),
            viewport: vp,
            transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null
          }).promise;
        }

        if (cancelled || serial !== renderSerial) return;

        // Swap the complete rendered document into view in one operation.
        host.replaceChildren(...Array.from(staging.childNodes));
        pageRefs.current = nextPageRefs;

        const firstPageScale = nextPageRefs[1]?.scale;
        if (typeof firstPageScale === "number") {
          setScale(firstPageScale);
        }

        pane.scrollTop = Math.min(
          previousScrollTop,
          Math.max(0, pane.scrollHeight - pane.clientHeight)
        );

        setStatus("ready");
        onReadyRef.current?.(pdf.numPages);
      } catch (err) {
        if (!cancelled && serial === renderSerial) {
          setStatus("failed");
        }
      }
    }

    // One clean initial render.
    renderDocument(true);

    // Browser resize includes normal window changes and browser zoom changes.
    // We deliberately do not observe the scrollable pane itself.
    const handleResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        renderDocument();
      }, 160);
    };

    window.addEventListener("resize", handleResize);

    return () => {
      cancelled = true;
      renderSerial += 1;
      window.clearTimeout(resizeTimer);
      window.removeEventListener("resize", handleResize);
    };
  }, [file]);

  // Draw / move the evidence highlight.
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

      window.setTimeout(() => {
        target.holder.classList.remove("page-flash");
      }, 1600);
    }
  }, [highlight, scale]);

  return (
    <section className="docpane" ref={paneRef}>
      <div className="docinner" ref={hostRef} />
      {status === "failed" && (
        <div className="pane-msg">
          <h3>That PDF could not be rendered</h3>
          <p>
            ContractLens reads text-based digital contracts. Scans and photographs
            are out of scope.
          </p>
        </div>
      )}
    </section>
  );
}
