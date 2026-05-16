import React, { useRef, useState, useEffect } from "react";
import "./FileUpload.css";

const PIPELINE_STEPS = [
  { icon: "◈", label: "Parse & detect columns" },
  { icon: "⬡", label: "Compute RFM scores" },
  { icon: "◉", label: "Auto-select optimal k" },
  { icon: "▣", label: "Label customer segments" },
  { icon: "★", label: "Generate product recommendations" },
];

const SEGMENT_EXAMPLES = [
  { name: "Champions",     color: "#22d3ee", desc: "High value, recent, frequent" },
  { name: "Loyal",         color: "#a78bfa", desc: "Consistent, long-term buyers" },
  { name: "At Risk",       color: "#fb923c", desc: "Once great, now fading" },
  { name: "Lost",          color: "#f87171", desc: "Inactive, low engagement" },
];

export default function FileUpload({ onUpload, error }) {
  const inputRef    = useRef();
  const canvasRef   = useRef();
  const [dragging, setDragging]   = useState(false);
  const [fileName, setFileName]   = useState(null);
  const [stepIdx, setStepIdx]     = useState(0);

  // Animate pipeline steps cycling
  useEffect(() => {
    const id = setInterval(() => setStepIdx(i => (i + 1) % PIPELINE_STEPS.length), 1800);
    return () => clearInterval(id);
  }, []);

  // Subtle dot-grid canvas background
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const resize = () => {
      canvas.width  = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "rgba(56,189,248,0.18)";
      const gap = 28;
      for (let x = gap; x < canvas.width; x += gap)
        for (let y = gap; y < canvas.height; y += gap)
          ctx.fillRect(x - 1, y - 1, 1.5, 1.5);
    };
    resize();
    const obs = new ResizeObserver(resize);
    obs.observe(canvas);
    return () => obs.disconnect();
  }, []);

  const process = (file) => {
    if (!file) return;
    setFileName(file.name);
    onUpload(file);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    process(e.dataTransfer.files[0]);
  };

  return (
    <div className="lp-root">
      <canvas ref={canvasRef} className="lp-canvas" aria-hidden="true" />

      {/* ── Left column: identity + pipeline preview ── */}
      <div className="lp-left">
       

        <h1 className="lp-title">
          Turn raw transactions<br />
          into <span className="lp-title-accent">segment strategy</span>
        </h1>

        <p className="lp-body">
          Upload any retail CSV or Excel file. The engine auto-detects your columns,
          computes Recency · Frequency · Monetary scores, and finds the optimal number
          of customer clusters — no configuration needed.
        </p>

        {/* RFM trio */}
        <div className="lp-rfm-trio">
          {[
            { letter: "R", word: "Recency",   blurb: "Days since last purchase" },
            { letter: "F", word: "Frequency", blurb: "Number of transactions" },
            { letter: "M", word: "Monetary",  blurb: "Total customer spend" },
          ].map(({ letter, word, blurb }) => (
            <div key={letter} className="lp-rfm-card">
              <span className="lp-rfm-letter">{letter}</span>
              <span className="lp-rfm-word">{word}</span>
              <span className="lp-rfm-blurb">{blurb}</span>
            </div>
          ))}
        </div>

        {/* Animated pipeline preview */}
        <div className="lp-pipeline">
          <p className="lp-pipeline-label">What happens after upload</p>
          <div className="lp-pipeline-steps">
            {PIPELINE_STEPS.map((s, i) => (
              <div key={i} className={`lp-pipe-step ${i === stepIdx ? "lp-pipe-active" : ""} ${i < stepIdx ? "lp-pipe-done" : ""}`}>
                <span className="lp-pipe-icon">{i < stepIdx ? "✓" : s.icon}</span>
                <span className="lp-pipe-label">{s.label}</span>
              </div>
            ))}
          </div>
        </div>

        
      </div>

      {/* ── Right column: upload + column guide ── */}
      <div className="lp-right">

        {/* Drop zone */}
        <div
          className={`lp-drop ${dragging ? "lp-drop-over" : ""} ${error ? "lp-drop-err" : ""} ${fileName ? "lp-drop-ready" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && inputRef.current.click()}
          aria-label="Upload file"
        >
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            style={{ display: "none" }}
            onChange={(e) => process(e.target.files[0])}
          />

          <div className="lp-drop-inner">
            <div className={`lp-drop-orb ${dragging ? "lp-orb-pulse" : ""}`}>
              {fileName
                ? <span className="lp-orb-icon">✓</span>
                : dragging
                  ? <span className="lp-orb-icon">↓</span>
                  : <span className="lp-orb-icon">⬆</span>
              }
            </div>

            {fileName ? (
              <>
                <p className="lp-drop-main lp-drop-filename">{fileName}</p>
                <p className="lp-drop-sub">Processing…</p>
              </>
            ) : (
              <>
                <p className="lp-drop-main">Drop your dataset here</p>
                <p className="lp-drop-sub">or click to browse</p>
              </>
            )}

            <div className="lp-fmt-badges">
              {[".csv", ".xlsx", ".xls"].map(f => (
                <span key={f} className="lp-fmt-badge">{f}</span>
              ))}
              <span className="lp-fmt-badge lp-fmt-size">any size</span>
            </div>
          </div>
        </div>

        {error && (
          <div className="lp-error">
            <span className="lp-error-icon">⚠</span>
            <span>{error}</span>
          </div>
        )}

        {/* Column auto-detection guide */}
        <div className="lp-cols-card">
          <div className="lp-cols-header">
            <span className="lp-cols-icon">⬡</span>
            <span className="lp-cols-title">Auto-detected columns</span>
          </div>

          <div className="lp-cols-list">
            <ColRow
              label="Customer ID"
              required
              tag="REQUIRED"
              examples="Customer_Name · CustomerID · UserID · Client_ID"
              purpose="Groups all transactions per customer"
            />
            <ColRow
              label="Spend / Amount"
              required
              tag="REQUIRED"
              examples="Total_Cost · Total_Amount · UnitPrice · Price_per_Unit"
              purpose="Drives the Monetary dimension"
            />
            <ColRow
              label="Transaction ID"
              required
              tag="REQUIRED"
              examples="Transaction_ID · InvoiceNo · OrderID"
              purpose="Enables accurate Frequency counting"
            />
            <ColRow
              label="Date"
              required
              tag="REQUIRED"
              examples="Date · InvoiceDate · Transaction_Date · OrderDate"
              purpose="Enables true Recency calculation"
            />
            <ColRow
              label="Quantity"
              required
              tag="REQUIRED"
              examples="Total_Items · Quantity · Qty"
              purpose="Combined with unit price when no total exists"
            />
          </div>

          <p className="lp-cols-note">
            If no date column is found, Recency is estimated from row order.&nbsp;
            Works with millions of rows — MiniBatchKMeans kicks in above 10 k customers.
          </p>
        </div>

        {/* Feature strip */}
        <div className="lp-features">
          {[
            { icon: "◉", text: "Silhouette-based auto k-selection (k=2…8)" },
            { icon: "⬡", text: "FP-Growth product recommendations per segment" },
            { icon: "◈", text: "AI-generated segment names & action plans" },
            { icon: "▣", text: "Full data analysis: distributions, top customers, trends" },
          ].map((f, i) => (
            <div key={i} className="lp-feature">
              <span className="lp-feature-icon">{f.icon}</span>
              <span className="lp-feature-text">{f.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ColRow({ label, required, tag, examples, purpose }) {
  return (
    <div className={`lp-col-row ${required ? "lp-col-required" : ""}`}>
      <div className="lp-col-top">
        <span className="lp-col-label">{label}</span>
        <span className={`lp-col-tag ${required ? "lp-tag-req" : "lp-tag-opt"}`}>{tag}</span>
      </div>
      <span className="lp-col-purpose">{purpose}</span>
      <span className="lp-col-examples">{examples}</span>
    </div>
  );
}
