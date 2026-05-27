import React, { useState, useEffect, useCallback } from "react";
import {
BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
LineChart, Line, CartesianGrid, Cell, PieChart, Pie, Legend,
} from "recharts";
import "./DataAnalysis.css";

const API = "http://localhost:8000";

const COLORS = ["#1d4ed8","#0f766e","#b45309","#7c3aed","#be123c",
"#0369a1","#15803d","#c2410c","#0891b2","#6d28d9"];

/* ────────────────────────────────────────────────────────────
   Reusable chart tooltip info icon
──────────────────────────────────────────────────────────── */
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

export default function DataAnalysis({ initialData, file }) {
  // initialData arrives instantly from the /process stream (no extra fetch needed)
  const [data,       setData]      = useState(initialData || null);
  const [sessionId,  setSessionId] = useState(initialData?.session_id || null);
  const [loading,    setLoading]   = useState(false);
  const [error,      setError]     = useState(null);
  const [topN,       setTopN]      = useState(10);
  const [dateStart,  setDateStart] = useState(initialData?.date_min || "");
  const [dateEnd,    setDateEnd]   = useState(initialData?.date_max || "");
  const [productTab, setProductTab] = useState("revenue");

  // Sync if parent passes new initialData (new file upload)
  useEffect(() => {
    if (initialData) {
      setData(initialData);
      setSessionId(initialData.session_id || null);
      setDateStart(initialData.date_min || "");
      setDateEnd(initialData.date_max || "");
    }
  }, [initialData]);

  const fetch_data = useCallback(async (start, end, n) => {
    setLoading(true);
    setError(null);
    const fd = new FormData();
    fd.append("top_n", n);
    if (start) fd.append("date_start", start);
    if (end)   fd.append("date_end",   end);

    if (sessionId) {
      // Fast path: server already has the df in memory — no file needed
      fd.append("session_id", sessionId);
    } else if (file) {
      // Fallback: session expired, re-upload the file
      fd.append("file", file);
    } else {
      return;
    }

    try {
      const res = await fetch(`${API}/analyze`, { method: "POST", body: fd });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || "Analysis failed");
      setData(json);
      if (json.session_id) setSessionId(json.session_id);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sessionId, file]);

  const handleApply = () => fetch_data(dateStart, dateEnd, topN);

  if (loading && !data) return <AnalysisLoader />;
  if (error)   return <AnalysisError msg={error} onRetry={() => fetch_data(dateStart, dateEnd, topN)} />;
  if (!data)   return null;

  const { summary, top_products_revenue, top_products_quantity, monthly_trend,
          weekday_data, has_date, date_min, date_max, filtered_rows } = data;

  const productData = productTab === "revenue" ? top_products_revenue : top_products_quantity;
  const productKey  = productTab === "revenue" ? "revenue" : "quantity";
  const productFmt  = productTab === "revenue"
    ? (v) => `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    : (v) => Number(v).toLocaleString();

  return (
    <div className="da-root">
      {/* ── Page header ── */}
      <div className="da-header">
        <div>
          <h1 className="da-title">Data Analysis</h1>
          <p className="da-sub">
            {filtered_rows.toLocaleString()} transactions
            {has_date && date_min && ` · ${date_min} to ${date_max}`}
          </p>
        </div>

        {/* ── Filters ── */}
        <div className="da-filters">
          {has_date && (
            <>
              <div className="filter-group">
                <label className="filter-label">From</label>
                <input type="date" className="filter-input"
                  value={dateStart} min={date_min} max={date_max}
                  onChange={e => setDateStart(e.target.value)} />
              </div>
              <div className="filter-group">
                <label className="filter-label">To</label>
                <input type="date" className="filter-input"
                  value={dateEnd} min={date_min} max={date_max}
                  onChange={e => setDateEnd(e.target.value)} />
              </div>
            </>
          )}
          <div className="filter-group">
            <label className="filter-label">Top N</label>
            <select className="filter-input filter-select"
              value={topN} onChange={e => setTopN(Number(e.target.value))}>
              {[5, 10, 15, 20].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <button className="apply-btn" onClick={handleApply} disabled={loading}>
            {loading ? "Loading…" : "Apply"}
          </button>
        </div>
      </div>

      {/* ── KPI cards ── */}
      <div className="da-kpis">
        <KpiCard label="Total Revenue"   value={`$${Number(summary.total_revenue).toLocaleString(undefined, { maximumFractionDigits: 2 })}`} color="blue" />
        <KpiCard label="Total Orders"    value={summary.total_orders.toLocaleString()} color="teal" />
        <KpiCard label="Total Quantity"  value={summary.total_qty.toLocaleString()} color="amber" />
        <KpiCard label="Avg Order Value"
          value={`$${summary.total_orders > 0 ? (summary.total_revenue / summary.total_orders).toFixed(2) : "0"}`}
          color="violet" />
      </div>

      {/* ── Row 1: Revenue trend + Weekday ── */}
      {has_date && monthly_trend?.length > 0 && (
        <div className="da-row">
          <div className="da-card da-card-wide">
            <p className="da-card-title">
              Monthly Revenue
              <ChartTooltip
                title="Monthly Revenue Trend"
                description="Shows total revenue generated per month across the dataset's date range."
                interpretation="Each point on the line represents the total sales amount for that month. Rising lines indicate growth; drops may signal seasonal slowdowns, lost customers, or inventory issues."
                tip="Hover over any point to see the exact revenue for that month. Use the date filters above to zoom into specific periods."
              />
            </p>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={monthly_trend} margin={{ left: 0, right: 16, top: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--muted)", fontFamily: "IBM Plex Mono" }}
                  axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: "var(--muted)", fontFamily: "IBM Plex Mono" }}
                  axisLine={false} tickLine={false}
                  tickFormatter={v => `$${(v/1000).toFixed(0)}k`} />
                <Tooltip contentStyle={TOOLTIP_STYLE}
                  formatter={v => [`$${Number(v).toLocaleString()}`, "Revenue"]} />
                <Line type="monotone" dataKey="revenue" stroke="#1d4ed8" strokeWidth={2}
                  dot={false} activeDot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {weekday_data?.length > 0 && (
            <div className="da-card">
              <p className="da-card-title">
                Revenue by Day of Week
                <ChartTooltip
                  title="Revenue by Day of Week"
                  description="Shows which days of the week generate the most revenue across all transactions in the dataset."
                  interpretation="Taller bars = more revenue on that day. This reveals customer purchasing habits — for example, weekends may spike for retail, while B2B businesses may peak mid-week."
                  tip="Use this to decide the best days to run promotions, send email campaigns, or staff up for high-demand periods."
                />
              </p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={weekday_data} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="weekday" tick={{ fontSize: 10, fill: "var(--muted)" }}
                    axisLine={false} tickLine={false}
                    tickFormatter={d => d.slice(0, 3)} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--muted)", fontFamily: "IBM Plex Mono" }}
                    axisLine={false} tickLine={false}
                    tickFormatter={v => `$${(v/1000).toFixed(0)}k`} />
                  <Tooltip contentStyle={TOOLTIP_STYLE}
                    formatter={v => [`$${Number(v).toLocaleString()}`, "Revenue"]} />
                  <Bar dataKey="revenue" radius={[4,4,0,0]}>
                    {weekday_data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* ── Row 2: Top N products ── */}
      {(top_products_revenue?.length > 0 || top_products_quantity?.length > 0) && (
        <div className="da-card">
        <div className="da-card-header">
        <p className="da-card-title">
              Top {topN} Products
              <ChartTooltip
                title="Top Products Chart"
                description="Ranks your best-selling products either by total revenue earned or by total quantity sold, depending on the selected tab."
                interpretation="By Revenue shows which products contribute most to total sales value. By Quantity shows which products move the most units — these may differ (e.g. a cheap high-volume item vs an expensive low-volume one)."
                tip="Switch between the Revenue and Quantity tabs to compare. Use the Top N filter above the page to adjust how many products are shown."
              />
            </p>
            <div className="tab-toggle">
              <button className={`tab-btn ${productTab === "revenue" ? "tab-active" : ""}`}
                onClick={() => setProductTab("revenue")}>By Revenue</button>
              <button className={`tab-btn ${productTab === "quantity" ? "tab-active" : ""}`}
                onClick={() => setProductTab("quantity")}>By Quantity</button>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={Math.max(240, productData.length * 36)}>
            <BarChart data={[...productData].reverse()} layout="vertical"
              margin={{ left: 8, right: 32, top: 4, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: "var(--muted)", fontFamily: "IBM Plex Mono" }}
                axisLine={false} tickLine={false}
                tickFormatter={v => productTab === "revenue" ? `$${(v/1000).toFixed(0)}k` : v.toLocaleString()} />
              <YAxis type="category" dataKey="product" width={220}
                tick={{ fontSize: 11, fill: "var(--text2)" }} axisLine={false} tickLine={false}
                tickFormatter={v => v.length > 32 ? v.slice(0, 30) + "…" : v} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={v => [productFmt(v), productTab === "revenue" ? "Revenue" : "Qty"]} />
              <Bar dataKey={productKey} radius={[0,4,4,0]}>
                {productData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────
function KpiCard({ label, value, color }) {
  return (
    <div className={`kpi-card kpi-${color}`}>
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
    </div>
  );
}

function AnalysisLoader() {
  return (
    <div className="da-loader">
      <div className="da-spinner" />
      <p>Loading analysis…</p>
    </div>
  );
}

function AnalysisError({ msg, onRetry }) {
  return (
    <div className="da-error">
      <p className="da-error-title">Analysis failed</p>
      <p className="da-error-msg">{msg}</p>
      <button className="apply-btn" onClick={onRetry}>Retry</button>
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
