import React, { useState } from "react";
import "./ProcessingReport.css";

const TABS = [
  { key: "overview",  label: "Overview" },
  { key: "raw",       label: "Raw Data" },
  { key: "cleaned",   label: "Cleaned Data" },
  { key: "rfm",       label: "RFM Table" },
  { key: "scaled",    label: "Scaled Features" },
];

export default function ProcessingReport({ report, onClose }) {
  const [tab, setTab] = useState("overview");

  return (
    <div className="report-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="report-drawer">

        {/* ── Header ── */}
        <div className="report-header">
          <div>
            <h2 className="report-title">Processing Report</h2>
            <p className="report-sub">A full breakdown of every step applied to your dataset</p>
          </div>
          <button className="report-close" onClick={onClose}>✕</button>
        </div>

        {/* ── Tabs ── */}
        <div className="report-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`report-tab ${tab === t.key ? "active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Body ── */}
        <div className="report-body">
          {tab === "overview"  && <OverviewTab  report={report} />}
          {tab === "raw"       && <PreviewTab   preview={report.raw_preview}     label="Raw dataset — first 8 rows as loaded from file" />}
          {tab === "cleaned"   && <PreviewTab   preview={report.cleaned_preview} label="After preprocessing — zero/negative amounts and missing IDs removed" />}
          {tab === "rfm"       && <RFMTab       preview={report.rfm_preview}     stats={report.rfm_stats} />}
          {tab === "scaled"    && <ScaledTab    preview={report.scaled_preview}  stats={report.scaled_stats} />}
        </div>
      </div>
    </div>
  );
}

/* ── Overview tab ─────────────────────────────────────────────────────────── */
function OverviewTab({ report }) {
  const {
    rows_raw, rows_cleaned, rows_dropped_total,
    unique_customers, preprocessing_steps,
  } = report;

  const pctKept = ((rows_cleaned / rows_raw) * 100).toFixed(1);

  return (
    <div className="overview-tab">

      {/* Summary cards */}
      <div className="ov-cards">
        <OvCard label="Raw rows"         value={rows_raw.toLocaleString()} />
        <OvCard label="After cleaning"   value={rows_cleaned.toLocaleString()} color="green" />
        <OvCard label="Rows removed"     value={rows_dropped_total.toLocaleString()} color="amber" />
        <OvCard label="Rows retained"    value={`${pctKept}%`} />
        <OvCard label="Unique customers" value={unique_customers.toLocaleString()} color="blue" />
      </div>

      {/* Preprocessing steps table */}
      <div className="ov-section">
        <h3 className="ov-section-title">Preprocessing Steps</h3>
        <div className="steps-table">
          <div className="st-head">
            <span>Step</span>
            <span>Before</span>
            <span>After</span>
            <span>Removed</span>
            <span>Note</span>
          </div>
          {preprocessing_steps.map((s, i) => (
            <div key={i} className="st-row">
              <span className="st-step">{s.step}</span>
              <span>{s.before.toLocaleString()}</span>
              <span>{s.after.toLocaleString()}</span>
              <span className={s.removed > 0 ? "st-removed" : ""}>{s.removed.toLocaleString()}</span>
              <span className="st-note">{s.note}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Pipeline sequence */}
      <div className="ov-section">
        <h3 className="ov-section-title">Full Pipeline Sequence</h3>
        <ol className="pipeline-list">
          <li>Load raw file → parse rows and columns</li>
          <li>Map column names to canonical RFM roles</li>
          <li>Remove rows with missing or blank Customer IDs</li>
          <li>Compute monetary amount per row (or use existing total column)</li>
          <li>Drop rows with zero or negative monetary values</li>
          <li>Aggregate Frequency per customer (distinct transactions or row count)</li>
          <li>Aggregate Monetary per customer (sum of amounts)</li>
          <li>Compute Recency per customer (days since last purchase, or row-order proxy)</li>
          <li>Merge R, F, M into one customer-level RFM table</li>
          <li>Apply log1p transformation to reduce skewness</li>
          <li>Standardize with StandardScaler (mean=0, std=1)</li>
          <li>Test k=2 through k=8 using K-Means, score with Silhouette</li>
          <li>Fit final model with best k</li>
          <li>Assign segment labels based on composite R·F·M rank</li>
        </ol>
      </div>
    </div>
  );
}

function OvCard({ label, value, color }) {
  return (
    <div className={`ov-card ov-card-${color || "default"}`}>
      <span className="ov-card-value">{value}</span>
      <span className="ov-card-label">{label}</span>
    </div>
  );
}

/* ── Generic preview tab ──────────────────────────────────────────────────── */
function PreviewTab({ preview, label }) {
  if (!preview) return <p className="tab-empty">No data available.</p>;
  const { columns, rows, total_rows, total_cols } = preview;

  return (
    <div className="preview-tab">
      <p className="preview-meta">
        Showing first {rows.length} of <strong>{total_rows.toLocaleString()}</strong> rows
        &nbsp;·&nbsp; {total_cols} columns
        {label && <> &nbsp;·&nbsp; <em>{label}</em></>}
      </p>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c) => <th key={c}>{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => <td key={j}>{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── RFM table tab ────────────────────────────────────────────────────────── */
function RFMTab({ preview, stats }) {
  return (
    <div className="rfm-tab">
      {/* Stats */}
      <div className="ov-section">
        <h3 className="ov-section-title">Distribution Summary (before scaling)</h3>
        <div className="stats-grid">
          {Object.entries(stats).map(([col, s]) => (
            <div key={col} className="stat-card">
              <p className="stat-card-title">{col}</p>
              <div className="stat-rows">
                <StatRow label="Min"    value={s.min} />
                <StatRow label="Max"    value={s.max} />
                <StatRow label="Mean"   value={s.mean} />
                <StatRow label="Median" value={s.median} />
                <StatRow label="Std"    value={s.std} />
              </div>
            </div>
          ))}
        </div>
      </div>
      {/* Preview */}
      <PreviewTab preview={preview} label="Aggregated RFM values per customer" />
    </div>
  );
}

/* ── Scaled features tab ─────────────────────────────────────────────────── */
function ScaledTab({ preview, stats }) {
  return (
    <div className="rfm-tab">
      <div className="ov-section">
        <h3 className="ov-section-title">After log1p + StandardScaler</h3>
        <p className="ov-note">
          Each feature was first log-transformed (log1p) to reduce skewness, then
          standardized so mean ≈ 0 and std ≈ 1. These are the values fed into K-Means.
        </p>
        <div className="stats-grid">
          {Object.entries(stats).map(([col, s]) => (
            <div key={col} className="stat-card">
              <p className="stat-card-title">{col.replace("_scaled", "")}</p>
              <div className="stat-rows">
                <StatRow label="Min"  value={s.min} />
                <StatRow label="Max"  value={s.max} />
                <StatRow label="Mean" value={s.mean} />
                <StatRow label="Std"  value={s.std} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <PreviewTab preview={preview} label="Scaled values used as K-Means input" />
    </div>
  );
}

function StatRow({ label, value }) {
  return (
    <div className="stat-row">
      <span className="stat-row-label">{label}</span>
      <span className="stat-row-value">{typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : value}</span>
    </div>
  );
}
