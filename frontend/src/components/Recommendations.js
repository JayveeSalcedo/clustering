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
  const [viewMode,      setViewMode]      = useState("cards");
  const [showLog,       setShowLog]       = useState(false);

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

      <div className="rec-header">
        <div>
          <h1 className="rec-title">Product Recommendations</h1>
          <p className="rec-sub">
            Discover which products are frequently bought together using association rule mining.
          </p>
        </div>
      </div>

      <div className="rec-controls-card">
        <div className="rec-tab-row">
          <button className={`rec-tab ${tab === "all"     ? "rec-tab-active" : ""}`} onClick={() => setTab("all")}>🌐 All Customers</button>
          <button className={`rec-tab ${tab === "segment" ? "rec-tab-active" : ""}`} onClick={() => setTab("segment")}>👥 By Segment</button>
        </div>

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

      {error && (
        <div className="rec-error">
          <span className="rec-error-icon">⚠️</span>
          <div>
            <p className="rec-error-title">Couldn't generate recommendations</p>
            <p className="rec-error-msg">{error}</p>
          </div>
        </div>
      )}

      {result && (
        <ResultsPanel
          result={result}
          tab={tab}
          viewMode={viewMode}
          setViewMode={setViewMode}
          segmentLabel={segmentLabel}
          onShowLog={() => setShowLog(true)}
        />
      )}

      {showLog && result && (
        <RecommendationLog
          log={result.process_log}
          params={result.params}
          onClose={() => setShowLog(false)}
        />
      )}

    </div>
  );
}

// ── Results panel ─────────────────────────────────────────────────────────────
function ResultsPanel({ result, tab, viewMode, setViewMode, segmentLabel, onShowLog }) {
  const { rules, n_transactions, n_products, segment_name, empty_reason } = result;

  const emptyMessages = {
    support_too_high:    "No product combinations met the popularity threshold. Try lowering the Popularity slider.",
    confidence_too_high: "Patterns were found but none were reliable enough. Try lowering the Reliability slider.",
  };

  return (
    <div className="rec-results">
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

        <div className="rec-actions-row">
          {rules.length > 0 && (
            <>
              <div className="rec-view-toggle">
                <button
                  className={`rec-view-btn ${viewMode === "cards" ? "active" : ""}`}
                  onClick={() => setViewMode("cards")}
                >⊞ Cards</button>
                <button
                  className={`rec-view-btn ${viewMode === "table" ? "active" : ""}`}
                  onClick={() => setViewMode("table")}
                >☰ Table</button>
              </div>
              <button
                className="rec-export-btn"
                onClick={() => exportCSV(rules, segmentLabel)}
              >⬇ Export CSV</button>
            </>
          )}
          <button className="rec-log-btn" onClick={onShowLog}>
            📋 Process Log
          </button>
        </div>
      </div>

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

// ── Recommendation Process Log Modal ─────────────────────────────────────────
function RecommendationLog({ log, params, onClose }) {
  const statusIcon = (s) =>
    s === "ok"   ? <span className="rlog-icon rlog-ok">✓</span>  :
    s === "warn" ? <span className="rlog-icon rlog-warn">⚠</span> :
    s === "skip" ? <span className="rlog-icon rlog-skip">—</span> :
                   <span className="rlog-icon rlog-ok">✓</span>;

  return (
    <div className="report-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="report-drawer">

        {/* Header */}
        <div className="report-header">
          <div>
            <h2 className="report-title">Recommendation Process Log</h2>
            <p className="report-sub">Step-by-step breakdown of how the FP-Growth algorithm ran</p>
          </div>
          <button className="report-close" onClick={onClose}>✕</button>
        </div>

        <div className="report-body">

          {/* Params used */}
          {params && (
            <div className="ov-section" style={{ marginBottom: 24 }}>
              <h3 className="ov-section-title">Parameters Used</h3>
              <div className="ov-cards">
                <OvCard label="Min Support"    value={`${(params.min_support * 100).toFixed(1)}%`}  color="blue" />
                <OvCard label="Min Confidence" value={`${(params.min_confidence * 100).toFixed(0)}%`} color="blue" />
                <OvCard label="Top N Rules"    value={params.top_n} />
                <OvCard label="Segment"        value={params.segment_name || "All customers"} color="green" />
                <OvCard label="Frequent Sets"  value={(params.n_frequent_items || 0).toLocaleString()} color="amber" />
                <OvCard label="Rules Generated" value={(params.n_rules_before_limit || 0).toLocaleString()} color="amber" />
              </div>
            </div>
          )}

          {/* Pipeline steps */}
          <div className="ov-section" style={{ marginBottom: 24 }}>
            <h3 className="ov-section-title">Pipeline Steps</h3>
            <div className="rlog-steps">
              {(log || []).map((entry, i) => (
                <div key={i} className={`rlog-row rlog-row-${entry.status}`}>
                  <div className="rlog-left">
                    {statusIcon(entry.status)}
                    <span className="rlog-step-name">{entry.step}</span>
                  </div>
                  <span className="rlog-detail">{entry.detail}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Algorithm explanation */}
          <div className="ov-section">
            <h3 className="ov-section-title">How FP-Growth Works</h3>
            <ol className="pipeline-list">
              <li>Retrieve the cached DataFrame from session memory (uploaded file data)</li>
              <li>Detect invoice and product columns from column alias mapping</li>
              <li>Optionally filter rows to only the selected customer segment using KMeans labels</li>
              <li>Clean the working data — drop null or blank invoice and product values</li>
              <li>Build a boolean basket matrix: rows = invoices, columns = products, True = purchased</li>
              <li>Run FP-Growth on the basket matrix to find all frequent item sets above min_support</li>
              <li>Derive association rules from frequent item sets filtered by min_confidence</li>
              <li>Sort all rules by lift (descending) and return the top N strongest rules</li>
            </ol>
          </div>

          {/* Metric guide */}
          <div className="ov-section" style={{ marginTop: 24 }}>
            <h3 className="ov-section-title">Metric Reference</h3>
            <div className="rlog-metric-guide">
              <div className="rlog-metric-row">
                <span className="rlog-metric-name">Support</span>
                <span className="rlog-metric-formula">P(A ∪ B)</span>
                <span className="rlog-metric-desc">Fraction of all transactions containing both products. Filters out rare flukes.</span>
              </div>
              <div className="rlog-metric-row">
                <span className="rlog-metric-name">Confidence</span>
                <span className="rlog-metric-formula">P(A ∪ B) / P(A)</span>
                <span className="rlog-metric-desc">Of all orders with product A, what fraction also had B. Measures reliability.</span>
              </div>
              <div className="rlog-metric-row">
                <span className="rlog-metric-name">Lift</span>
                <span className="rlog-metric-formula">confidence / P(B)</span>
                <span className="rlog-metric-desc">How much more likely B is given A vs random chance. Above 1 = genuine relationship. Used for ranking.</span>
              </div>
            </div>
          </div>

        </div>
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

// ── CARD VIEW ─────────────────────────────────────────────────────────────────
function CardsView({ rules }) {
  const top3    = rules.slice(0, 3);
  const theRest = rules.slice(3);
  return (
    <div className="rec-cards-root">
      <div className="rec-spotlight-label">
        <span className="rec-spotlight-icon">⭐</span>
        Top bundle opportunities
      </div>
      <div className="rec-spotlight-strip">
        {top3.map((rule, i) => <SpotlightCard key={i} rule={rule} rank={i + 1} />)}
      </div>
      {theRest.length > 0 && (
        <>
          <div className="rec-spotlight-label" style={{ marginTop: 8 }}>
            <span className="rec-spotlight-icon">📦</span>
            All {rules.length} bundles — sorted by lift
          </div>
          <div className="rec-card-grid">
            {rules.map((rule, i) => <BundleCard key={i} rule={rule} rank={i + 1} />)}
          </div>
        </>
      )}
    </div>
  );
}

function SpotlightCard({ rule, rank }) {
  const meta    = liftMeta(rule.lift);
  const antText = rule.antecedents.join(" + ");
  const conText = rule.consequents.join(" + ");
  const pct     = Math.round(rule.confidence * 100);
  return (
    <div className="rec-spotlight-card" style={{ borderColor: meta.border }}>
      <div className="rec-spotlight-rank">#{rank}</div>
      <div className="rec-spotlight-lift-badge" style={{ background: meta.bg, color: meta.text, borderColor: meta.border }}>
        {meta.icon} {meta.label} · ×{rule.lift.toFixed(2)}
      </div>
      <p className="rec-spotlight-sentence">
        Customers who buy <strong>{antText}</strong> are{" "}
        <span className="rec-spotlight-multiplier">×{rule.lift.toFixed(1)}</span> more likely to also buy{" "}
        <strong>{conText}</strong>.
      </p>
      <div className="rec-spotlight-meta">
        <span>{pct}% of the time this pairing occurs</span>
        <span className="rec-spotlight-dot">·</span>
        <span>Seen in {(rule.support * 100).toFixed(1)}% of all orders</span>
      </div>
    </div>
  );
}

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
      <div className="rec-bundle-flow">
        <div className="rec-bundle-side">
          <span className="rec-bundle-side-label">If they buy</span>
          <div className="rec-bundle-tags">
            {rule.antecedents.map((p, i) => <span key={i} className="rec-product-tag rec-product-if">{p}</span>)}
          </div>
        </div>
        <div className="rec-bundle-arrow">→</div>
        <div className="rec-bundle-side">
          <span className="rec-bundle-side-label">Recommend</span>
          <div className="rec-bundle-tags">
            {rule.consequents.map((p, i) => <span key={i} className="rec-product-tag rec-product-then">{p}</span>)}
          </div>
        </div>
      </div>
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
                <div className="rec-mini-bar-wrap">
                  <div className="rec-mini-bar" style={{ width: `${Math.min(rule.support / 0.2, 1) * 100}%`, background: "#bfdbfe" }} />
                </div>
              </span>
              <span className="rec-metric">
                <span className="rec-metric-val">{(rule.confidence * 100).toFixed(0)}%</span>
                <div className="rec-mini-bar-wrap">
                  <div className="rec-mini-bar" style={{ width: `${rule.confidence * 100}%`, background: "#bbf7d0" }} />
                </div>
              </span>
              <span className="rec-metric">
                <span className="rec-lift-badge" style={{
                  background: liftMeta(rule.lift).bg,
                  color: liftMeta(rule.lift).text,
                  borderColor: liftMeta(rule.lift).border,
                }}>
                  {liftMeta(rule.lift).icon} ×{rule.lift.toFixed(2)}
                  <span className="rec-lift-label">{liftMeta(rule.lift).label}</span>
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
