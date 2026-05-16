import React, { useState, useRef, useEffect } from "react";
import FileUpload from "./components/FileUpload";
import Results from "./components/Results";
import DataAnalysis from "./components/DataAnalysis";
import Recommendations from "./components/Recommendations";
import FloatingChatButton from "./components/FloatingChatButton";
import "./App.css";

const API = "http://localhost:8000";

export default function App() {
  const [phase, setPhase]           = useState("upload");    // upload | app
  const [activeNav, setNav]         = useState("analysis");  // analysis | segment
  const [fileObj, setFileObj]       = useState(null);

  // Analysis state — available almost immediately
  const [analysisData, setAnalysis] = useState(null);

  // Clustering state — arrives later via streaming
  const [clusterResult, setCluster] = useState(null);        // null = not done yet
  const [clusterSteps, setSteps]    = useState([]);
  const [clusterError, setClusterError] = useState(null);
  const [clusterDone, setClusterDone]   = useState(false);

  const handleUpload = async (file) => {
    setFileObj(file);
    setPhase("app");
    setNav("analysis");
    setAnalysis(null);
    setCluster(null);
    setSteps([{ stage: "__start__", status: "running", title: `Reading "${file.name}"…`, lines: [] }]);
    setClusterError(null);
    setClusterDone(false);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("top_n", 10);

    try {
      const res = await fetch(`${API}/process`, { method: "POST", body: formData });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Server error"); }

      const reader = res.body.getReader();
      const dec    = new TextDecoder();
      let   buf    = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();

        for (const part of parts) {
          if (!part.trim()) continue;
          let evType = "message", dataLine = "";
          for (const line of part.split("\n")) {
            if (line.startsWith("event: ")) evType   = line.slice(7).trim();
            if (line.startsWith("data: "))  dataLine = line.slice(6).trim();
          }
          if (!dataLine) continue;
          let payload;
          try { payload = JSON.parse(dataLine); } catch { continue; }

          if (evType === "analysis") {
            // Analysis arrives first — populate Data Analysis tab immediately
            setAnalysis(payload);
          } else if (evType === "step") {
            setSteps(prev => {
              const next = prev.map(s => s.status === "running" ? { ...s, status: "done" } : s);
              next.push({
                stage: payload.stage, status: "running", title: payload.title,
                detail: payload.detail || "", warn: payload.warn || false,
                lines: buildLines(payload),
              });
              return next;
            });
          } else if (evType === "error") {
            setSteps(prev => prev.map((s, i) => i === prev.length - 1 ? { ...s, status: "error" } : s));
            setClusterError(payload.message || "Pipeline error");
          } else if (evType === "done") {
            setSteps(prev => prev.map(s => s.status === "running" ? { ...s, status: "done" } : s));
            setCluster(payload);
            setClusterDone(true);
          }
        }
      }
    } catch (e) {
      setClusterError(e.message);
      setSteps(prev => prev.map((s, i) => i === prev.length - 1 ? { ...s, status: "error" } : s));
    }
  };

  const handleReset = () => {
    setPhase("upload"); setFileObj(null);
    setAnalysis(null); setCluster(null); setSteps([]);
    setClusterError(null); setClusterDone(false); setNav("analysis");
  };

  // Build AI context for floating chat
  const aiContext = analysisData && clusterResult ? {
    profiles: clusterResult.profiles,
    meta: clusterResult.meta,
    summary: {
      total_customers: clusterResult.total_customers,
      total_transactions: clusterResult.total_transactions,
      total_revenue: analysisData?.summary?.total_revenue ?? 0,
      total_orders: analysisData?.summary?.total_orders ?? 0,
      best_k: clusterResult.best_k,
      best_silhouette: clusterResult.silhouette_scores?.[clusterResult.best_k] ?? 0,
    },
    analysis: analysisData ?? {},
    top_products_revenue: analysisData?.top_products_revenue ?? [],
    top_products_quantity: analysisData?.top_products_quantity ?? [],
    monthly_trend: analysisData?.monthly_trend ?? [],
    weekday_data: analysisData?.weekday_data ?? [],
  } : null;

  return (
    <>
      <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-mark">▣</span>
            <span className="logo-text">RFM<span className="logo-accent">seg</span></span>
          </div>
          <p className="header-sub">Customer Segmentation and Product Recommendation Engine</p>
          {phase === "app" && (
            <button className="header-new-file" onClick={handleReset}>↩ New file</button>
          )}
        </div>
      </header>

      {phase === "upload" && (
        <main className="main">
          <FileUpload onUpload={handleUpload} />
        </main>
      )}

      {phase === "app" && (
        <div className="app-shell">
          {/* ── Sidebar ── */}
          <aside className="sidebar">
            <div className="sidebar-file-badge">
              <span className="sidebar-file-icon">📁</span>
              <span className="sidebar-file-name" title={fileObj?.name}>{fileObj?.name}</span>
            </div>
            <nav className="sidebar-nav">
              <NavItem
                icon="📊" label="Data Analysis" id="analysis"
                active={activeNav} onClick={setNav}
                badge={analysisData ? null : "loading"}
              />
              <NavItem
                icon="👥" label="Customer Segmentation" id="segment"
                active={activeNav} onClick={setNav}
                badge={clusterDone ? null : "running"}
              />
              <NavItem
                icon="🛒" label="Recommendations" id="recommend"
                active={activeNav} onClick={setNav}
                badge={!clusterDone ? "locked" : null}
                disabled={!clusterDone}
              />
            </nav>

            {/* Mini cluster progress in sidebar */}
            {!clusterDone && clusterSteps.length > 0 && (
              <div className="sidebar-progress">
                <div className="sidebar-progress-bar">
                  <div className="sidebar-progress-fill"
                    style={{ width: `${Math.round((clusterSteps.filter(s => s.status === "done").length / 14) * 100)}%` }} />
                </div>
                <p className="sidebar-progress-label">
                  {clusterSteps[clusterSteps.length - 1]?.title || "Processing…"}
                </p>
              </div>
            )}
            {clusterDone && (
              <div className="sidebar-done">✓ Segmentation ready</div>
            )}
          </aside>

          {/* ── Content ── */}
          <div className="app-content">
            {activeNav === "analysis" && (
              analysisData
                ? <DataAnalysis initialData={analysisData} file={fileObj} />
                : <AnalysisPlaceholder />  // already correct
            )}
            {activeNav === "segment" && (
              clusterResult
                ? <Results data={clusterResult} onReset={handleReset} analysisData={analysisData} />
                : <ClusteringInProgress steps={clusterSteps} error={clusterError} onReset={handleReset} />
            )}
            {activeNav === "recommend" && clusterResult && (
              <Recommendations
                sessionId={analysisData?.session_id}
                profiles={clusterResult.profiles}
              />
            )}
          </div>
        </div>
      )}
    </div>

    {/* Floating Chat Button - always available */}
    <FloatingChatButton context={aiContext} />
    </>
  );
}

// ── Nav item with optional badge ───────────────────────────────────────────────
function NavItem({ icon, label, id, active, onClick, badge, disabled }) {
  return (
    <button
      className={`nav-item ${active === id ? "nav-active" : ""} ${disabled ? "nav-disabled" : ""}`}
      onClick={() => !disabled && onClick(id)}
      title={disabled ? "Available after segmentation completes" : undefined}
    >
      <span className="nav-icon">{icon}</span>
      <span className="nav-label">{label}</span>
      {badge === "loading" && <span className="nav-badge nav-badge-loading"><PulseDot /></span>}
      {badge === "running" && <span className="nav-badge nav-badge-running"><PulseDot /></span>}
      {badge === "locked"  && <span className="nav-badge-locked">🔒</span>}
    </button>
  );
}

function PulseDot() {
  return <span className="pulse-dot" />;
}

// ── Placeholder while analysis loads ──────────────────────────────────────────
function AnalysisPlaceholder() {
  return (
    <div className="placeholder-state">
      <div className="placeholder-spinner" />
      <p className="placeholder-title">Loading analysis…</p>
      <p className="placeholder-sub">Parsing your dataset — this takes a few seconds</p>
    </div>
  );
}

// ── Clustering in-progress panel ──────────────────────────────────────────────
function ClusteringInProgress({ steps, error, onReset }) {
  const bottomRef = useRef(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [steps.length]);

  const done  = steps.filter(s => s.status === "done").length;
  const total = 14; // approximate total steps
  const pct   = Math.min(Math.round((done / total) * 100), 99);

  return (
    <div className="cluster-progress-page">
      <div className="cp-header">
        <div>
          <h2 className="cp-title">Building Customer Segments</h2>
          <p className="cp-sub">Running RFM analysis and K-Means clustering</p>
        </div>
        <div className="cp-pct">{error ? "—" : `${pct}%`}</div>
      </div>

      {!error && (
        <div className="cp-track-wrap">
          <div className="cp-track">
            <div className="cp-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      <div className="pipeline-feed">
        {steps.map((step, i) => (
          <StepBlock key={`${step.stage}-${i}`} step={step} isLast={i === steps.length - 1} />
        ))}
        {error && (
          <div className="step-error-block">
            <span className="step-error-icon">✖</span>
            <div>
              <p className="step-error-title">Something went wrong</p>
              <p className="step-error-msg">{error}</p>
            </div>
            <button className="retry-btn" onClick={onReset}>↩ Try again</button>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ── Step block ─────────────────────────────────────────────────────────────────
const STAGE_ICONS = {
  __start__: "📁", parse: "📂", columns: "🔍", clean: "🧹", monetary: "💰",
  frequency: "🔁", monetary_agg: "📊", recency: "📅", rfm: "🧮",
  scale: "⚖️", best_k: "✅", profiles: "🏷️",
};

function StepBlock({ step, isLast }) {
  const isDone    = step.status === "done";
  const isRunning = step.status === "running";
  const isError   = step.status === "error";
  const icon      = STAGE_ICONS[step.stage] ?? (step.stage?.startsWith("k") ? "🔬" : "⚙️");
  const silLine   = step.lines?.find(l => l?.type === "sil");
  const bestK     = silLine ? Object.entries(silLine.scores).sort((a, b) => b[1] - a[1])[0]?.[0] : null;

  return (
    <div className={`step-block ${isDone ? "step-done" : ""} ${isRunning ? "step-running" : ""} ${isError ? "step-error" : ""} ${step.warn ? "step-warn" : ""}`}>
      <div className="step-node">
        {isDone    && <span className="node-check">✓</span>}
        {isRunning && <ThreeDots />}
        {isError   && <span className="node-x">✕</span>}
      </div>
      {!isLast && <div className="step-connector" />}
      <div className="step-content">
        <div className="step-head">
          <span className="step-emoji">{icon}</span>
          <span className="step-title-text">{step.title}</span>
        </div>
        {step.lines?.length > 0 && step.stage !== "__start__" && (
          <div className="step-body">
            {step.lines.map((line, i) => {
              if (line?.type === "sil") {
                const entries   = Object.entries(line.scores);
                const maxScore  = Math.max(...entries.map(([, v]) => v));
                return (
                  <div key={i} className="sil-inline">
                    <p className="sil-inline-label">Silhouette scores</p>
                    {entries.map(([k, v]) => (
                      <div key={k} className="sil-inline-row">
                        <span className="sil-k">k={k}</span>
                        <div className="sil-track">
                          <div className={`sil-fill ${String(k) === String(bestK) ? "sil-best" : ""}`}
                               style={{ width: `${(v / maxScore) * 100}%` }} />
                        </div>
                        <span className={`sil-score ${String(k) === String(bestK) ? "sil-score-best" : ""}`}>
                          {v.toFixed(4)}{String(k) === String(bestK) ? " ← best" : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              }
              return (
                <div key={i} className="step-line">
                  <span className="step-line-bullet">–</span>
                  <span className="step-line-text">{line}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function buildLines(payload) {
  const lines = [];
  if (payload.detail) payload.detail.split(/\s+·\s+/).forEach(p => { if (p.trim()) lines.push(p.trim()); });
  if (payload.sil_scores) lines.push({ type: "sil", scores: payload.sil_scores });
  return lines;
}

function ThreeDots() {
  return (
    <span className="three-dots">
      <span className="dot" /><span className="dot" /><span className="dot" />
    </span>
  );
}
