import React, { useState, useCallback } from "react";
import "./Recommendations.css";

const API = "http://localhost:8000";

const TERM_INFO = {
  support: {
    label: "Popularity",
    icon: "📊",
    explain:
      "How often these products appear together in ALL your transactions. " +
      "1% means 1 in every 100 orders contains this combination. " +
      "Lower = rarer bundles but more of them. Higher = only very common pairs.",
    default: 0.02,
    min: 0.001,
    max: 0.2,
    step: 0.001,
    format: (v) => `${(v * 100).toFixed(1)}%`,
  },
  confidence: {
    label: "Reliability",
    icon: "🎯",
    explain:
      "Out of all orders containing the first product(s), how many ALSO contain the recommended product. " +
      "50% means half the time a customer buys product A, they also buy product B. " +
      "Higher = stronger, more reliable recommendations.",
    default: 0.2,
    min: 0.05,
    max: 0.99,
    step: 0.01,
    format: (v) => `${(v * 100).toFixed(0)}%`,
  },
};

const ERROR_MESSAGES = {
  no_invoice:
    "Your dataset doesn't have an order/invoice ID column. Bundle detection requires knowing which products were bought in the same transaction.",
  no_product:
    "Your dataset doesn't have a product/description column. Bundle detection requires product names.",
  not_enough_transactions:
    "Not enough transactions in this segment to find reliable patterns. Try using 'All Customers' instead.",
  not_enough_products:
    "This segment only has one type of product — bundles need at least 2.",
};

// ── CSV export helper ─────────────────────────────────────────────────────────
function exportCSV(rules, segmentLabel) {
  const header = ["Antecedents", "Consequents", "Support", "Confidence", "Lift"];
  const rows = rules.map((r) => [
    `"${r.antecedents.join(", ")}"`,
    `"${r.consequents.join(", ")}"`,
    r.support.toFixed(4),
    r.confidence.toFixed(4),
    r.lift.toFixed(4),
  ]);
  const csv = [header, ...rows].map((r) => r.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `bundle_rules${segmentLabel ? "_" + segmentLabel.replace(/\s+/g, "_") : ""}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Lift label helper ─────────────────────────────────────────────────────────
function liftMeta(lift) {
  if (lift >= 3) return { label: "Very strong", icon: "🔥", bg: "#fef3c7", text: "#92400e", border: "#fde68a" };
  if (lift >= 2) return { label: "Strong",      icon: "✅", bg: "#f0fdf4", text: "#15803d", border: "#bbf7d0" };
  return            { label: "Moderate",         icon: "〰",  bg: "#f1f5f9", text: "#64748b", border: "#e2e8f0" };
}

export default function Recommendations({ sessionId, profiles }) {
  const [tab,           setTab]           = useState("all");
  const [clusterId,     setClusterId]     = useState(profiles[0]?.cluster ?? 1);
  const [minSupport,    setMinSupport]    = useState(0.02);
  const [minConfidence, setMinConfidence] = useState(0.2);
  const [result,        setResult]        = useState(null);
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState(null);
  const [tooltip,       setTooltip]       = useState(null);
  // "table" | "cards" — view toggle
  const [viewMode,      setViewMode]      = useState("cards");

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/recommend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id:     sessionId,
          cluster_id:     tab === "segment" ? clusterId : null,
          min_support:    minSupport,
          min_confidence: minConfidence,
          top_n:          30,
          profiles,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        const detail = data.detail || "";
        setError(ERROR_MESSAGES[detail] || detail || "Something went wrong.");
        return;
      }
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId, tab, clusterId, minSupport, minConfidence, profiles]);

  const activeProfile = profiles.find((p) => p.cluster === clusterId);
  const segmentLabel  = tab === "segment" ? (result?.segment_name || activeProfile?.segment) : null;

  return (
    <div className="rec-root">
      {/* ── Page header ── */}
      <div className="rec-header">
        <div>
          <h1 className="rec-title">Product Recommendations</h1>
          <p className="rec-sub">
            Discover which products are frequently bought together using association rule mining.
          </p>
        </div>
      </div>

      {/* ── Controls card ── */}
      <div className="rec-controls-card">
        {/* Tab: All vs Segment */}
        <div className="rec-tab-row">
          <button className={`rec-tab ${tab === "all"     ? "rec-tab-active" : ""}`} onClick={() => setTab("all")}>🌐 All Customers</button>
          <button className={`rec-tab ${tab === "segment" ? "rec-tab-active" : ""}`} onClick={() => setTab("segment")}>👥 By Segment</button>
        </div>

        {/* Segment picker */}
        {tab === "segment" && (
          <div className="rec-segment-picker">
            <p className="rec-control-label">Choose a customer segment</p>
            <div className="rec-segment-chips">
              {profiles.map((p) => (
                <button
                  key={p.cluster}
                  className={`rec-segment-chip ${clusterId === p.cluster ? "active" : ""}`}
                  onClick={() => setClusterId(p.cluster)}
                >
                  {p.segment}
                  <span className="rec-chip-pct">{p.pct_customers}%</span>
                </button>
              ))}
            </div>
            {activeProfile && (
              <p className="rec-segment-hint">
                Mining bundles from <strong>{activeProfile.size.toLocaleString()}</strong> customers
                in <strong>{activeProfile.segment}</strong>
                {activeProfile.description ? ` — ${activeProfile.description}` : ""}
              </p>
            )}
          </div>
        )}

        {/* Threshold sliders */}
        <div className="rec-thresholds">
          {["support", "confidence"].map((key) => {
            const info = TERM_INFO[key];
            const val  = key === "support" ? minSupport : minConfidence;
            const set  = key === "support" ? setMinSupport : setMinConfidence;
            return (
              <div key={key} className="rec-threshold-group">
                <div className="rec-threshold-header">
                  <span className="rec-threshold-icon">{info.icon}</span>
                  <span className="rec-threshold-label">{info.label}</span>
                  <span className="rec-threshold-value">{info.format(val)}</span>
                  <button className="rec-info-btn" onClick={() => setTooltip(tooltip === key ? null : key)}>?</button>
                </div>
                {tooltip === key && (
                  <div className="rec-tooltip">
                    <p>{info.explain}</p>
                    <button className="rec-tooltip-close" onClick={() => setTooltip(null)}>✕ Close</button>
                  </div>
                )}
                <div className="rec-slider-row">
                  <span className="rec-slider-bound">{info.format(info.min)}</span>
                  <input
                    type="range"
                    className="rec-slider"
                    min={info.min} max={info.max} step={info.step} value={val}
                    onChange={(e) => set(parseFloat(e.target.value))}
                  />
                  <span className="rec-slider-bound">{info.format(info.max)}</span>
                </div>
                <p className="rec-slider-hint">
                  {key === "support"
                    ? val < 0.01 ? "Very low — will find rare but interesting combos"
                    : val < 0.05 ? "Balanced — good starting point"
                    : "High — only very common bundles"
                    : val < 0.3  ? "Low — more suggestions, less certain"
                    : val < 0.6  ? "Balanced — reasonable confidence"
                    : "High — only very strong patterns"}
                </p>
              </div>
            );
          })}
        </div>

        <button className="rec-run-btn" onClick={run} disabled={loading}>
          {loading ? <><span className="rec-spinner" /> Finding patterns…</> : "🔍 Find Product Bundles"}
        </button>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="rec-error">
          <span className="rec-error-icon">⚠️</span>
          <div>
            <p className="rec-error-title">Couldn't generate recommendations</p>
            <p className="rec-error-msg">{error}</p>
          </div>
        </div>
      )}

      {/* ── Results ── */}
      {result && (
        <ResultsPanel
          result={result}
          minSupport={minSupport}
          minConfidence={minConfidence}
          tab={tab}
          viewMode={viewMode}
          setViewMode={setViewMode}
          segmentLabel={segmentLabel}
        />
      )}
    </div>
  );
}

// ── Results panel ─────────────────────────────────────────────────────────────
function ResultsPanel({ result, tab, viewMode, setViewMode, segmentLabel }) {
  const { rules, n_transactions, n_products, segment_name, empty_reason } = result;

  const emptyMessages = {
    support_too_high:    "No product combinations met the popularity threshold. Try lowering the Popularity slider.",
    confidence_too_high: "Patterns were found but none were reliable enough. Try lowering the Reliability slider.",
  };

  return (
    <div className="rec-results">
      {/* Stats bar + actions row */}
      <div className="rec-results-topbar">
        <div className="rec-stats-bar">
          <div className="rec-stat">
            <span className="rec-stat-value">{n_transactions.toLocaleString()}</span>
            <span className="rec-stat-label">
              {tab === "segment" && segment_name ? `${segment_name} transactions` : "Transactions analysed"}
            </span>
          </div>
          <div className="rec-stat">
            <span className="rec-stat-value">{n_products.toLocaleString()}</span>
            <span className="rec-stat-label">Unique products</span>
          </div>
          <div className="rec-stat">
            <span className="rec-stat-value">{rules.length}</span>
            <span className="rec-stat-label">Rules found</span>
          </div>
        </div>

        {/* View toggle + export */}
        {rules.length > 0 && (
          <div className="rec-actions-row">
            <div className="rec-view-toggle">
              <button
                className={`rec-view-btn ${viewMode === "cards" ? "active" : ""}`}
                onClick={() => setViewMode("cards")}
                title="Card view"
              >⊞ Cards</button>
              <button
                className={`rec-view-btn ${viewMode === "table" ? "active" : ""}`}
                onClick={() => setViewMode("table")}
                title="Table view"
              >☰ Table</button>
            </div>
            <button
              className="rec-export-btn"
              onClick={() => exportCSV(rules, segmentLabel)}
              title="Download rules as CSV"
            >⬇ Export CSV</button>
          </div>
        )}
      </div>

      {/* Empty state */}
      {rules.length === 0 ? (
        <div className="rec-empty">
          <p className="rec-empty-icon">🔎</p>
          <p className="rec-empty-title">No patterns found</p>
          <p className="rec-empty-sub">{emptyMessages[empty_reason] || "Try adjusting the sliders and running again."}</p>
        </div>
      ) : viewMode === "cards" ? (
        <CardsView rules={rules} />
      ) : (
        <TableView rules={rules} />
      )}
    </div>
  );
}

// ── CARD VIEW ─────────────────────────────────────────────────────────────────
function CardsView({ rules }) {
  const top3    = rules.slice(0, 3);
  const theRest = rules.slice(3);

  return (
    <div className="rec-cards-root">
      {/* ── Spotlight strip: top 3 ── */}
      <div className="rec-spotlight-label">
        <span className="rec-spotlight-icon">⭐</span>
        Top bundle opportunities
      </div>
      <div className="rec-spotlight-strip">
        {top3.map((rule, i) => (
          <SpotlightCard key={i} rule={rule} rank={i + 1} />
        ))}
      </div>

      {/* ── All rules as cards ── */}
      {theRest.length > 0 && (
        <>
          <div className="rec-spotlight-label" style={{ marginTop: 8 }}>
            <span className="rec-spotlight-icon">📦</span>
            All {rules.length} bundles — sorted by lift
          </div>
          <div className="rec-card-grid">
            {rules.map((rule, i) => (
              <BundleCard key={i} rule={rule} rank={i + 1} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// Spotlight card — large format, plain-English sentence
function SpotlightCard({ rule, rank }) {
  const meta      = liftMeta(rule.lift);
  const antText   = rule.antecedents.join(" + ");
  const consText  = rule.consequents.join(" + ");
  const pct       = Math.round(rule.confidence * 100);

  return (
    <div className="rec-spotlight-card" style={{ borderColor: meta.border }}>
      <div className="rec-spotlight-rank">#{rank}</div>
      <div className="rec-spotlight-lift-badge" style={{ background: meta.bg, color: meta.text, borderColor: meta.border }}>
        {meta.icon} {meta.label} · ×{rule.lift.toFixed(2)}
      </div>
      <p className="rec-spotlight-sentence">
        Customers who buy <strong>{antText}</strong> are{" "}
        <span className="rec-spotlight-multiplier">×{rule.lift.toFixed(1)}</span> more likely to also buy{" "}
        <strong>{consText}</strong>.
      </p>
      <div className="rec-spotlight-meta">
        <span>{pct}% of the time this pairing occurs</span>
        <span className="rec-spotlight-dot">·</span>
        <span>Seen in {(rule.support * 100).toFixed(1)}% of all orders</span>
      </div>
    </div>
  );
}

// Bundle card — compact, visual arrow layout
function BundleCard({ rule, rank }) {
  const meta = liftMeta(rule.lift);
  return (
    <div className="rec-bundle-card">
      <div className="rec-bundle-card-header">
        <span className="rec-bundle-rank">#{rank}</span>
        <span className="rec-bundle-lift-badge" style={{ background: meta.bg, color: meta.text, borderColor: meta.border }}>
          {meta.icon} ×{rule.lift.toFixed(2)}
        </span>
      </div>

      {/* Product flow: IF → THEN */}
      <div className="rec-bundle-flow">
        <div className="rec-bundle-side">
          <span className="rec-bundle-side-label">If they buy</span>
          <div className="rec-bundle-tags">
            {rule.antecedents.map((p, i) => (
              <span key={i} className="rec-product-tag rec-product-if">{p}</span>
            ))}
          </div>
        </div>
        <div className="rec-bundle-arrow">→</div>
        <div className="rec-bundle-side">
          <span className="rec-bundle-side-label">Recommend</span>
          <div className="rec-bundle-tags">
            {rule.consequents.map((p, i) => (
              <span key={i} className="rec-product-tag rec-product-then">{p}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Metrics row */}
      <div className="rec-bundle-metrics">
        <div className="rec-bundle-metric">
          <span className="rec-bundle-metric-label">Popularity</span>
          <div className="rec-mini-bar-wrap">
            <div className="rec-mini-bar" style={{ width: `${Math.min(rule.support / 0.2, 1) * 100}%`, background: "#bfdbfe" }} />
          </div>
          <span className="rec-bundle-metric-val">{(rule.support * 100).toFixed(1)}%</span>
        </div>
        <div className="rec-bundle-metric">
          <span className="rec-bundle-metric-label">Reliability</span>
          <div className="rec-mini-bar-wrap">
            <div className="rec-mini-bar" style={{ width: `${rule.confidence * 100}%`, background: "#bbf7d0" }} />
          </div>
          <span className="rec-bundle-metric-val">{(rule.confidence * 100).toFixed(0)}%</span>
        </div>
      </div>
    </div>
  );
}

// ── TABLE VIEW (original layout, preserved) ───────────────────────────────────
function TableView({ rules }) {
  return (
    <>
      <div className="rec-legend">
        <span><strong>If a customer buys</strong> the items on the left →</span>
        <span>they are likely to also buy the item(s) on the right.</span>
        <span className="rec-legend-tip">Sorted by Lift (strongest relationship first).</span>
      </div>
      <div className="rec-table-wrap">
        <div className="rec-table">
          <div className="rec-thead">
            <span>If customer buys…</span>
            <span>They'll likely also buy</span>
            <span><span className="rec-th-with-tip">Popularity<span className="rec-th-sub">how common</span></span></span>
            <span><span className="rec-th-with-tip">Reliability<span className="rec-th-sub">how often true</span></span></span>
            <span><span className="rec-th-with-tip">Lift<span className="rec-th-sub">strength of link</span></span></span>
          </div>
          {rules.map((rule, i) => (
            <div key={i} className={`rec-row ${i % 2 === 0 ? "rec-row-alt" : ""}`}>
              <span className="rec-products">
                {rule.antecedents.map((p, j) => <span key={j} className="rec-product-tag rec-product-if">{p}</span>)}
              </span>
              <span className="rec-products">
                {rule.consequents.map((p, j) => <span key={j} className="rec-product-tag rec-product-then">{p}</span>)}
              </span>
              <span className="rec-metric">
                <span className="rec-metric-val">{(rule.support * 100).toFixed(1)}%</span>
                <SupportBar value={rule.support} />
              </span>
              <span className="rec-metric">
                <span className="rec-metric-val">{(rule.confidence * 100).toFixed(0)}%</span>
                <ConfidenceBar value={rule.confidence} />
              </span>
              <span className="rec-metric">
                <LiftBadge lift={rule.lift} />
              </span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ── Small reusable visual helpers ─────────────────────────────────────────────
function SupportBar({ value }) {
  return (
    <div className="rec-mini-bar-wrap">
      <div className="rec-mini-bar" style={{ width: `${Math.min(value / 0.2, 1) * 100}%`, background: "#bfdbfe" }} />
    </div>
  );
}

function ConfidenceBar({ value }) {
  return (
    <div className="rec-mini-bar-wrap">
      <div className="rec-mini-bar" style={{ width: `${value * 100}%`, background: "#bbf7d0" }} />
    </div>
  );
}

function LiftBadge({ lift }) {
  const meta = liftMeta(lift);
  return (
    <span className="rec-lift-badge" style={{ background: meta.bg, color: meta.text, borderColor: meta.border }}>
      {meta.icon} ×{lift.toFixed(2)}
      <span className="rec-lift-label">{meta.label}</span>
    </span>
  );
}
