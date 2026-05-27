import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  Tooltip, Cell
} from "recharts";
import ProcessingReport from "./ProcessingReport";
import "./Results.css";
import "./AiPanel.css";

const API = "http://localhost:8000";

const ACCENT_COLORS = [
  "#1d4ed8", "#0f766e", "#b45309", "#7c3aed",
  "#be123c", "#0369a1", "#15803d", "#c2410c",
];

const SEGMENT_ICONS = {
  "Champions":           "🏆",
  "Loyal Customers":     "💎",
  "Potential Loyalists": "🌱",
  "At Risk":             "⚠️",
  "Cannot Lose Them":    "🔥",
  "Hibernating":         "❄️",
  "Lost Customers":      "💤",
  "New Customers":       "✨",
};

function getIcon(name) {
  if (!name) return "◉";
  for (const [key, icon] of Object.entries(SEGMENT_ICONS)) {
    if (name.toLowerCase().includes(key.toLowerCase())) return icon;
  }
  return "◉";
}

// ── A: Revenue share per segment ─────────────────────────────────────────────
// Estimates each segment's share of total revenue using mean_monetary × size.
// This is a proxy — not exact transaction-level revenue — but directionally correct
// and requires no extra API call.
function computeRevenueShares(profiles) {
  const totals = profiles.map(p => p.mean_monetary * p.size);
  const grand  = totals.reduce((a, b) => a + b, 0);
  return totals.map(t => grand > 0 ? Math.round((t / grand) * 100) : 0);
}



// ── C: Silhouette quality label ───────────────────────────────────────────────
function silhouetteQuality(score) {
  if (score >= 0.5) return { label: "Good separation",  color: "#15803d" };
  if (score >= 0.3) return { label: "Fair separation",  color: "#92400e" };
  return                   { label: "Weak separation",  color: "#b91c1c" };
}

// ── D: "What to do" action hint per segment ───────────────────────────────────
// Pure rule-based logic — no AI call. Derived from the segment name.
function getActionHint(profile) {
  const name   = (profile.segment || "").toLowerCase();

  if (name.includes("champion") || name.includes("loyal"))
    return "💡 Reward loyalty — offer exclusive deals or early access to new products.";
  if (name.includes("potential") || name.includes("new"))
    return "💡 Nurture — send onboarding emails and first-purchase incentives.";
  if (name.includes("hibernat") || name.includes("lost"))
    return "💡 Last-chance campaign — deep discount or reactivation offer before writing off.";
  return "💡 Re-engage — targeted promotions or personalized offers to maintain engagement.";
}

function escapeCSV(value) {
  if (value === null || value === undefined) return "";
  const str = String(value);
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

function exportSegmentsCSV(profiles) {
  const header = [
    "Cluster",
    "Segment",
    "Customers",
    "PctCustomers",
    "MeanRecency",
    "MeanFrequency",
    "MeanMonetary",
    "MedianRecency",
    "MedianFrequency",
    "MedianMonetary",
    "Description",
  ];
  const rows = profiles.map((p) => [
    p.cluster,
    p.segment,
    p.size,
    p.pct_customers,
    p.mean_recency,
    p.mean_frequency,
    p.mean_monetary,
    p.median_recency,
    p.median_frequency,
    p.median_monetary,
    p.description || "",
  ]);
  const csv = [header, ...rows].map((row) => row.map(escapeCSV).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = "customer_segments.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export default function Results({ data, onReset, analysisData }) {
  const [activeCluster, setActiveCluster] = useState(0);
  const [showReport,    setShowReport]    = useState(false);

  const {
    total_customers, total_transactions, best_k,
    silhouette_scores, profiles, columns_detected, meta, report,
  } = data;

  const active      = profiles[activeCluster];
  const color       = ACCENT_COLORS[activeCluster % ACCENT_COLORS.length];
  const hasProxyRecency = meta && !meta.has_true_recency;

  // Pre-compute derived data for all profiles
  const revShares   = computeRevenueShares(profiles);
  const bestSilScore = silhouette_scores[best_k];
  const silQuality  = silhouetteQuality(bestSilScore);

  const maxM = Math.max(...profiles.map(p => p.mean_monetary));

  const silData = Object.entries(silhouette_scores).map(([k, v]) => ({
    k: `k=${k}`, score: v, best: parseInt(k) === best_k,
  }));

  const maxR = Math.max(...profiles.map(p => p.mean_recency));
  const maxF = Math.max(...profiles.map(p => p.mean_frequency));

  const radarData = [
    { metric: "Recency⁻¹", value: Math.round((1 - active.mean_recency / maxR) * 100) },
    { metric: "Frequency",  value: Math.round((active.mean_frequency  / maxF) * 100) },
    { metric: "Monetary",   value: Math.round((active.mean_monetary   / maxM) * 100) },
  ];

  const aiContext = {
    profiles,
    meta,
    summary: {
      total_customers,
      total_transactions,
      total_revenue: analysisData?.summary?.total_revenue ?? 0,
      total_orders:  analysisData?.summary?.total_orders  ?? 0,
      best_k,
      best_silhouette: bestSilScore,
    },
    analysis: analysisData ?? {},
    top_products_revenue:  analysisData?.top_products_revenue  ?? [],
    top_products_quantity: analysisData?.top_products_quantity ?? [],
    monthly_trend: analysisData?.monthly_trend ?? [],
    weekday_data:  analysisData?.weekday_data  ?? [],
  };

  return (
    <>
      <div className="results">

        {/* ══ SECTION 1: Header bar ══════════════════════════════════ */}
        <div className="results-header">
          <div className="results-header-left">
            <h1 className="results-title">Customer Segments</h1>
            <p className="results-subtitle">
              {total_customers.toLocaleString()} customers &nbsp;·&nbsp;
              {total_transactions.toLocaleString()} transactions &nbsp;·&nbsp;
              <span className="results-subtitle-accent">{best_k} segments</span>
            </p>
          </div>
          <div className="results-header-actions">
            {report && (
              <button className="ghost-btn" onClick={() => setShowReport(true)}>
                📋 Process Log
              </button>
            )}
            <button className="ghost-btn" onClick={() => exportSegmentsCSV(profiles)}>
              ⬇ Export CSV
            </button>
            <button className="ghost-btn" onClick={onReset}>↩ New file</button>
          </div>
        </div>

        {/* ══ SECTION 3: Meta pills row (moved above body, briefing goes bottom) */}
        <div className="meta-row">
          <div className="meta-pills">
            {/* C — Silhouette with quality label */}
            <span className="meta-pill">
              <span className="meta-pill-label">Silhouette</span>
              <span className="meta-pill-value">{bestSilScore.toFixed(4)}</span>
              <span className="meta-pill-quality" style={{ color: silQuality.color }}>
                {silQuality.label}
              </span>
            </span>
            {Object.entries(columns_detected).map(([k, v]) => (
              <span key={k} className="meta-pill">
                <span className="meta-pill-label">{k.replace(/_/g, " ")}</span>
                <span className="meta-pill-value">{v}</span>
              </span>
            ))}
          </div>
          {hasProxyRecency && (
            <div className="proxy-notice">
              <span className="proxy-icon">ℹ</span>
              <span>
                No date column — recency estimated from row order.
                {meta?.recency_source && <> Source: <code>{meta.recency_source}</code></>}
              </span>
            </div>
          )}
        </div>

        {/* ══ SECTION 4: Segment grid + detail ══════════════════════ */}
        <div className="results-body">

          {/* Left: segment cards */}
          <div className="cluster-list">
            <p className="section-label">Segments</p>
            {profiles.map((p, i) => {
              const revShare = revShares[i];
              return (
                <div
                  key={i}
                  className={`cluster-card ${i === activeCluster ? "active" : ""}`}
                  style={{ "--card-color": ACCENT_COLORS[i % ACCENT_COLORS.length] }}
                  onClick={() => setActiveCluster(i)}
                >

                  <div className="card-header">
                    <span className="card-icon">{getIcon(p.segment)}</span>
                    <div className="card-title-wrap">
                      <p className="card-segment">{p.segment}</p>
                      <p className="card-cluster">Cluster {p.cluster}</p>
                    </div>
                    <span className="card-pct">{p.pct_customers}%</span>
                  </div>
                  <div className="card-bar-wrap">
                    <div className="card-bar" style={{ width: `${p.pct_customers}%` }} />
                  </div>
                  <div className="card-stats">
                    <MiniStat label="R" value={`${p.mean_recency}${hasProxyRecency ? "" : "d"}`} />
                    <MiniStat label="F" value={p.mean_frequency} />
                    <MiniStat label="M" value={`$${p.mean_monetary >= 1000
                      ? (p.mean_monetary / 1000).toFixed(1) + "k"
                      : p.mean_monetary.toFixed(0)}`}
                    />
                  </div>
                  {/* A — revenue share badge */}
                  <div className="card-rev-share">
                    <span className="card-rev-share-bar-wrap">
                      <span className="card-rev-share-bar" style={{ width: `${revShare}%` }} />
                    </span>
                    <span className="card-rev-share-label">~{revShare}% of revenue</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Right: detail panel */}
          <div className="detail-panel">
            <div className="detail-header" style={{ "--panel-color": color }}>
              <span className="detail-icon">{getIcon(active.segment)}</span>
              <div className="detail-title-wrap">
                <div className="detail-title-row">
                  <h2 className="detail-segment">{active.segment}</h2>
                </div>
                <p className="detail-sub">
                  {active.size.toLocaleString()} customers &nbsp;·&nbsp;
                  {active.pct_customers}% of base &nbsp;·&nbsp;
                  {/* A — revenue share in subtitle */}
                  <span className="detail-rev-share">~{revShares[activeCluster]}% of revenue</span>
                </p>
                {active.description && (
                  <p className="detail-description">{active.description}</p>
                )}
              </div>
            </div>

            {/* D — Action hint strip */}
            <div className="action-hint">
              <span className="action-hint-text">{getActionHint(active)}</span>
            </div>

            <div className="metrics-grid">
              <MetricCard
                label={hasProxyRecency ? "Recency (proxy)" : "Avg. Recency"}
                mean={hasProxyRecency ? active.mean_recency : `${active.mean_recency}d`}
                median={hasProxyRecency ? active.median_recency : `${active.median_recency}d`}
                note={hasProxyRecency ? "Lower = more recent" : "Days since last purchase"}
                color={color}
              />
              <MetricCard
                label="Avg. Frequency"
                mean={active.mean_frequency}
                median={active.median_frequency}
                note={meta?.frequency_source || "Distinct transactions"}
                color={color}
              />
              <MetricCard
                label="Avg. Monetary"
                mean={`$${active.mean_monetary.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
                median={`$${active.median_monetary.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
                note={meta?.monetary_source || "Total spend"}
                color={color}
              />
            </div>

            <div className="charts-row">
              <div className="chart-box">
                <p className="chart-title">
                  RFM Profile
                  <ChartTooltip
                    title="RFM Radar Chart"
                    description="Shows the Recency, Frequency, and Monetary profile of the selected customer segment as a radar (spider) chart."
                    interpretation="Each axis is normalized 0–100 relative to the best-performing segment. A larger shaded area means a higher-value customer group. Recency⁻¹ is inverted — a higher score means customers purchased more recently."
                    tip="Compare shapes across segments by clicking each segment card on the left. A segment with a large triangle across all three axes represents your most valuable customers."
                  />
                </p>
                <ResponsiveContainer width="100%" height={200}>
                  <RadarChart data={radarData}>
                    <PolarGrid stroke="#e2e0db" />
                    <PolarAngleAxis
                      dataKey="metric"
                      tick={{ fill: "#8a8680", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                    />
                    <Radar dataKey="value" stroke={color} fill={color}
                      fillOpacity={0.15} strokeWidth={2} />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
              <div className="chart-box">
                <p className="chart-title">
                  Silhouette Scores
                  <ChartTooltip
                    title="Silhouette Score Chart"
                    description="The silhouette score measures how well-separated the customer clusters are. It is the primary metric used to automatically select the best number of segments (k)."
                    interpretation={`Each bar shows the silhouette score for a different number of clusters (k=2 to k=${Math.max(...silData.map(d => parseInt(d.k.replace('k=',''))))}).  The blue bar (k=${best_k}) was automatically selected because it achieved the highest score of ${bestSilScore.toFixed(4)}.`}
                    tip="Scores range from -1 to 1. Above 0.5 = good separation (clusters are distinct). 0.3–0.5 = fair. Below 0.3 = weak (clusters may overlap). The system always picks the k with the highest score so you never have to tune it manually."
                  />
                </p>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={silData} margin={{ left: -10 }}>
                    <XAxis dataKey="k"
                      tick={{ fill: "#8a8680", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                      axisLine={false} tickLine={false} />
                    <YAxis
                      tick={{ fill: "#8a8680", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                      axisLine={false} tickLine={false} domain={[0, 1]} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(0,0,0,0.03)" }}
                      formatter={(v, n) => [v.toFixed(4), "Silhouette Score"]}
                      labelFormatter={(l) => `${l}${silData.find(d=>d.k===l)?.best ? " ← selected" : ""}`}
                    />
                    <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                      {silData.map((e, i) => (
                        <Cell key={i} fill={e.best ? "#1d4ed8" : "#e2e0db"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <p className="chart-note">Blue = selected k={best_k} · Score: {bestSilScore.toFixed(4)} ({silQuality.label})</p>
              </div>
            </div>
          </div>
        </div>

        {/* ══ SECTION 5: Comparison table (full width) ══════════════ */}
        <div className="comparison-section">
          <p className="section-label" style={{ marginBottom: 12 }}>All Segments Comparison</p>
          <div className="comparison-table-wrap">
            <div className="comparison-table">
              {/* E — added Revenue Share and Monetary bar columns */}
              <div className="ct-head">
                <span>Segment</span>
                <span>Customers</span>
                <span>Share</span>
                <span>{hasProxyRecency ? "Recency*" : "Avg Recency"}</span>
                <span>Avg Frequency</span>
                <span>Avg Monetary</span>
                <span>~Rev Share</span>
              </div>
              {profiles.map((p, i) => {
                const revShare = revShares[i];
                const monWidth = maxM > 0 ? Math.round((p.mean_monetary / maxM) * 100) : 0;
                return (
                  <div
                    key={i}
                    className={`ct-row ${i === activeCluster ? "ct-active" : ""}`}
                    style={{ "--row-color": ACCENT_COLORS[i % ACCENT_COLORS.length] }}
                    onClick={() => setActiveCluster(i)}
                  >
                    <span className="ct-seg">
                      <span className="ct-dot" />
                      {p.segment}
                    </span>
                    <span>{p.size.toLocaleString()}</span>
                    <span>{p.pct_customers}%</span>
                    <span>{p.mean_recency}{hasProxyRecency ? "" : "d"}</span>
                    <span>{p.mean_frequency}</span>
                    {/* E — monetary with inline bar */}
                    <span className="ct-monetary-cell">
                      <span className="ct-monetary-val">
                        ${p.mean_monetary >= 1000
                          ? (p.mean_monetary / 1000).toFixed(1) + "k"
                          : p.mean_monetary.toFixed(2)}
                      </span>
                      <span className="ct-monetary-bar-wrap">
                        <span className="ct-monetary-bar"
                          style={{ width: `${monWidth}%`, background: ACCENT_COLORS[i % ACCENT_COLORS.length] }} />
                      </span>
                    </span>
                    {/* A — revenue share */}
                    <span className="ct-rev-share-cell">
                      <span className="ct-rev-share-val">~{revShare}%</span>
                      <span className="ct-rev-share-bar-wrap">
                        <span className="ct-rev-share-bar" style={{ width: `${revShare}%` }} />
                      </span>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
          {hasProxyRecency && (
            <p className="table-footnote">* Recency = row-order proxy (no date column)</p>
          )}
        </div>

        {/* ══ SECTION 6: AI tools ════════════════════════════════════ */}
        <div className="ai-section-divider">
          <span className="ai-section-label">✦ AI Tools</span>
        </div>

        <div className="ai-tools-grid">
          <ActionPlan profiles={profiles} meta={meta} summary={aiContext.summary} />
        </div>

        {/* ══ SECTION 7: AI Briefing (G — moved to bottom) ══════════ */}
        <AiBriefing
          profiles={profiles}
          meta={meta}
          summary={aiContext.summary}
          analysis={analysisData ?? {}}
        />

      </div>

      {showReport && (
        <ProcessingReport report={report} onClose={() => setShowReport(false)} />
      )}
    </>
  );
}

/* ─────────────────────────────────────────────────────────────
   AI BRIEFING — moved to bottom (G), dark-mode safe
───────────────────────────────────────────────────────────── */
function AiBriefing({ profiles, meta, summary, analysis }) {
  const [text,   setText]   = useState("");
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/ai/summary`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profiles, meta, summary, analysis }),
        });
        if (!res.ok) throw new Error("summary failed");
        const reader = res.body.getReader();
        const dec    = new TextDecoder();
        let   full   = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (cancelled) return;
          full += dec.decode(value, { stream: true });
          setText(full);
        }
        if (!cancelled) setStatus("done");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (status === "error") return null;

  return (
    <div className="ai-briefing">
      <div className="ai-briefing-label">
        <span className="ai-briefing-icon">🧠</span>
        AI Summary
      </div>
      <p className="ai-briefing-text">
        {text || <span className="ai-briefing-skeleton" />}
        {status === "loading" && text && <span className="ai-briefing-cursor" />}
      </p>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   ACTION PLAN
───────────────────────────────────────────────────────────── */
function ActionPlan({ profiles, meta, summary }) {
  const [status,   setStatus]   = useState("idle");
  const [markdown, setMarkdown] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const generate = async () => {
    setStatus("loading");
    setMarkdown("");
    setErrorMsg("");
    try {
      const res = await fetch(`${API}/ai/action-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profiles, meta, summary }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Request failed");
      }
      const reader = res.body.getReader();
      const dec    = new TextDecoder();
      let   full   = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        full += dec.decode(value, { stream: true });
        setMarkdown(full);
      }
      setStatus("done");
    } catch (e) {
      setErrorMsg(e.message);
      setStatus("error");
    }
  };

  const parseTable = (md) => {
    const lines = md.trim().split("\n").filter(l => l.trim().startsWith("|"));
    if (lines.length < 2) return null;
    const parseRow = l => l.split("|").slice(1, -1).map(c => c.trim());
    return { headers: parseRow(lines[0]), rows: lines.slice(2).map(parseRow) };
  };

  const table = status === "done" ? parseTable(markdown) : null;

  return (
    <div className="ai-tool-card">
      <div className="ai-tool-card-header">
        <div className="ai-tool-card-title"><span>📋</span> Action Plan</div>
        <button className="action-plan-btn" onClick={generate} disabled={status === "loading"}>
          {status === "loading" ? <><span className="ap-spinner" /> Generating…</>
           : status === "done"  ? <>↻ Regenerate</>
           : <>✨ Generate</>}
        </button>
      </div>
      {status === "idle" && (
        <p className="ai-tool-empty">Get AI-powered marketing recommendations for each segment.</p>
      )}
      {status === "loading" && !markdown && (
        <div className="action-plan-loading"><span className="ap-spinner" /> Asking AI for recommendations…</div>
      )}
      {status === "error" && <div className="action-plan-error">⚠️ {errorMsg}</div>}
      {markdown && (
        table ? (
          <div className="action-plan-table-wrap">
            <table>
              <thead><tr>{table.headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
              <tbody>{table.rows.map((row, i) => (
                <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
              ))}</tbody>
            </table>
          </div>
        ) : (
          <pre className="action-plan-raw">{markdown}</pre>
        )
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Small reusable components
───────────────────────────────────────────────────────────── */
/* ─────────────────────────────────────────────────────────────
   CHART TOOLTIP
───────────────────────────────────────────────────────────── */
function ChartTooltip({ title, description, interpretation, tip }) {
  const [visible, setVisible] = useState(false);
  return (
    <span
      className="chart-info-icon"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onClick={() => setVisible(v => !v)}
      aria-label="Chart explanation"
    >
      ?
      {visible && (
        <span className="chart-tooltip-box">
          <span className="ctt-title">{title}</span>
          {description && <span className="ctt-body">{description}</span>}
          {interpretation && (
            <span className="ctt-section">
              <span className="ctt-label">📊 What it shows</span>
              <span className="ctt-body">{interpretation}</span>
            </span>
          )}
          {tip && (
            <span className="ctt-section">
              <span className="ctt-label">💡 How to read it</span>
              <span className="ctt-body">{tip}</span>
            </span>
          )}
        </span>
      )}
    </span>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="mini-stat">
      <span className="mini-label">{label}</span>
      <span className="mini-value">{value}</span>
    </div>
  );
}

function MetricCard({ label, mean, median, note, color }) {
  return (
    <div className="metric-card" style={{ "--mc-color": color }}>
      <p className="mc-label">{label}</p>
      <p className="mc-mean">{mean}</p>
      <p className="mc-median">Median: {median}</p>
      <p className="mc-note">{note}</p>
    </div>
  );
}

const TOOLTIP_STYLE = {
  background: "#fff",
  border: "1px solid #e2e0db",
  borderRadius: 8,
  fontFamily: "IBM Plex Mono",
  fontSize: 12,
  color: "#1a1a1a",
  boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
};
