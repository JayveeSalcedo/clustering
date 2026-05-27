"""
RFM clustering pipeline.

PURPOSE:
    Transforms a raw transactional DataFrame into per-customer RFM scores,
    finds the optimal number of KMeans clusters via silhouette analysis,
    and uses the Groq LLM to give each cluster a business-readable name.

DATA SOURCE:
    Receives a Polars DataFrame already parsed from the user-uploaded file
    (CSV/XLSX/XLS, e.g. 'Online Retail.xlsx') by utils.read_file_fast().
    This function is a generator — it yields SSE-formatted strings that
    main.py:/process streams directly to the frontend, so the UI updates
    incrementally as each pipeline step completes.

PIPELINE STEPS (in order):
    1.  parse          — load acknowledgment + raw data preview
    2.  columns        — show resolved column mapping
    3.  clean          — remove rows with missing/blank Customer IDs
    4.  monetary       — compute/select the monetary value column
    5.  frequency      — count distinct invoices (or rows) per customer
    6.  monetary_agg   — sum monetary values per customer
    7.  recency        — compute days since last purchase (or row-order proxy)
    8.  rfm            — join R/F/M into a single customer-level table
    9.  scale          — log1p transform + StandardScaler normalisation
    10. k2–k8          — silhouette score for each candidate k
    11. best_k         — announce the winning k
    12. profiles       — per-cluster statistics
    13. done           — final payload with all results + report metadata
"""
import datetime
import json
import numpy as np
import polars as pl
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.metrics import silhouette_score

from app.config import get_groq, GROQ_MODEL
from app.session import store_labels
from app.utils import to_float, parse_dates, df_to_preview, sse


def run_clustering(df: pl.DataFrame, col_map: dict, session_id: str | None = None):
    """
    Generator — yields SSE strings for each pipeline step.

    Usage in main.py:
        yield from run_clustering(df, col_map, session_id)

    Each yielded string is a complete SSE message that the browser can parse.
    """
    total_rows  = len(df)
    # Capture a preview of the raw (unmodified) DataFrame for the report tab.
    raw_preview = df_to_preview(df)

    # ── Step 1: Acknowledge receipt of data ──────────────────────────────────
    yield sse("step", {"stage": "parse", "title": "Dataset loaded",
        "detail": f"{total_rows:,} rows · {len(df.columns)} columns"})

    # ── Step 2: Show resolved column mapping ─────────────────────────────────
    yield sse("step", {"stage": "columns", "title": "Columns mapped",
        "detail": "  ·  ".join(f"{k} -> {v}" for k, v in col_map.items())})

    cid_col = col_map["customer_id"]   # the actual column name in df
    meta: dict = {}                    # metadata collected for the final report
    preprocessing_steps: list = []    # list of dicts describing each cleaning step

    # ── Step 3: Clean customer IDs ────────────────────────────────────────────
    # Cast to string and strip whitespace so "12345 " == "12345".
    df = df.with_columns(
        pl.col(cid_col).cast(pl.Utf8).str.strip_chars().alias(cid_col)
    )
    before = len(df)
    # Remove rows where Customer ID is null, empty string, or literally "nan".
    df = df.filter(
        pl.col(cid_col).is_not_null() &
        (pl.col(cid_col) != "") &
        (pl.col(cid_col).str.to_lowercase() != "nan")
    )
    dropped_missing = before - len(df)
    preprocessing_steps.append({
        "step": "Remove missing Customer IDs", "before": before,
        "after": len(df), "removed": dropped_missing,
        "note": f"Dropped {dropped_missing:,} rows where Customer ID was blank or null",
    })
    yield sse("step", {"stage": "clean", "title": "Data cleaned",
        "detail": f"Removed {dropped_missing:,} rows with missing IDs · {len(df):,} rows remaining"})

    # ── Step 4: Compute monetary values ──────────────────────────────────────
    # Build a unified '_amount' column using the best available source.
    # Order of preference: total_amount > unit_price × quantity > quantity > unit_price
    if "total_amount" in col_map:
        df = to_float(df, col_map["total_amount"])
        df = df.with_columns(pl.col(col_map["total_amount"]).fill_null(0.0).alias("_amount"))
        meta["monetary_source"] = col_map["total_amount"]
    elif "unit_price" in col_map and "quantity" in col_map:
        # Revenue = quantity × price when neither is pre-computed.
        df = to_float(df, col_map["quantity"])
        df = to_float(df, col_map["unit_price"])
        df = df.with_columns(
            (pl.col(col_map["quantity"]).fill_null(0.0) *
             pl.col(col_map["unit_price"]).fill_null(0.0)).alias("_amount")
        )
        meta["monetary_source"] = f"{col_map['quantity']} x {col_map['unit_price']}"
    elif "quantity" in col_map:
        df = to_float(df, col_map["quantity"])
        df = df.with_columns(pl.col(col_map["quantity"]).fill_null(0.0).alias("_amount"))
        meta["monetary_source"] = col_map["quantity"]
    else:
        df = to_float(df, col_map["unit_price"])
        df = df.with_columns(pl.col(col_map["unit_price"]).fill_null(0.0).alias("_amount"))
        meta["monetary_source"] = col_map["unit_price"]

    # Drop rows with non-positive amounts (returns, cancellations, data errors).
    before_pos  = len(df)
    df          = df.filter(pl.col("_amount") > 0)
    dropped_neg = before_pos - len(df)
    preprocessing_steps.append({
        "step": "Remove zero/negative amounts", "before": before_pos,
        "after": len(df), "removed": dropped_neg,
        "note": f"Dropped {dropped_neg:,} rows with non-positive monetary values",
    })
    yield sse("step", {"stage": "monetary", "title": "Monetary values computed",
        "detail": f"Source: {meta['monetary_source']} · dropped {dropped_neg:,} invalid rows · "
                  f"total: ${df['_amount'].sum():,.2f}"})

    # Snapshot of the cleaned DataFrame for the report preview.
    cleaned_preview = df_to_preview(df)

    # ── Step 5: Compute Frequency (F) ────────────────────────────────────────
    # Frequency = number of distinct purchase events per customer.
    if "invoice_no" in col_map:
        inv_col  = col_map["invoice_no"]
        # Count unique invoice numbers per customer (preferred — avoids multi-line orders inflating count).
        freq_agg = df.group_by(cid_col).agg(pl.col(inv_col).n_unique().alias("Frequency"))
        meta["frequency_source"] = f"distinct {inv_col}"
    else:
        # No invoice column — count rows as a proxy for transaction count.
        freq_agg = df.group_by(cid_col).agg(pl.len().alias("Frequency"))
        meta["frequency_source"] = "row count per customer"

    yield sse("step", {"stage": "frequency", "title": "Frequency computed",
        "detail": f"Method: {meta['frequency_source']} · avg {freq_agg['Frequency'].mean():.1f} tx/customer"})

    # ── Step 6: Aggregate Monetary (M) ───────────────────────────────────────
    # Sum all transaction amounts per customer to get total spend.
    monetary_agg = df.group_by(cid_col).agg(pl.col("_amount").sum().alias("Monetary"))
    yield sse("step", {"stage": "monetary_agg", "title": "Monetary aggregated",
        "detail": f"Avg ${monetary_agg['Monetary'].mean():,.2f} · max ${monetary_agg['Monetary'].max():,.2f}"})

    # ── Step 7: Compute Recency (R) ───────────────────────────────────────────
    if "date" in col_map:
        date_col = col_map["date"]
        df       = parse_dates(df, date_col)               # normalise to pl.Date
        df       = df.filter(pl.col(date_col).is_not_null())  # drop unparseable dates

        max_date = df[date_col].max()

        # Safety net: if all dates failed to parse, fall back to row-order proxy
        if max_date is None:
            meta["has_true_recency"] = False
            meta["recency_source"]   = "row-order proxy (dates could not be parsed)"
            df      = df.with_row_index("_row_idx")
            max_idx = df["_row_idx"].max()
            recency_agg = (
                df.group_by(cid_col)
                .agg(pl.col("_row_idx").max().alias("_max_idx"))
                .with_columns(
                    (pl.lit(max_idx) - pl.col("_max_idx")).cast(pl.Int32).alias("Recency")
                )
                .select([cid_col, "Recency"])
            )
            yield sse("step", {
                "stage": "recency",
                "title": "Recency estimated (dates could not be parsed)",
                "detail": "Using row position as recency proxy — check your date column format",
                "warn": True,
            })
        else:
            # Use the day after the last transaction as the reference "today".
            analysis_date = max_date + datetime.timedelta(days=1)

            # Recency = days between a customer's last purchase and analysis_date.
            recency_agg = (
                df.group_by(cid_col)
                .agg(pl.col(date_col).max().alias("_last_date"))
                .with_columns(
                    (pl.lit(analysis_date) - pl.col("_last_date"))
                    .dt.total_days().cast(pl.Int32).alias("Recency")
                )
                .select([cid_col, "Recency"])
            )
            meta["recency_source"]   = f"days since last {date_col}"
            meta["has_true_recency"] = True
            yield sse("step", {"stage": "recency", "title": "Recency computed",
                "detail": f"{df[date_col].min()} to {max_date} · avg {recency_agg['Recency'].mean():.0f} days"})
    else:
        # No date column — use row position as a recency proxy.
        # Higher row index ≈ more recent; recency = max_idx - customer's last row idx.
        df      = df.with_row_index("_row_idx")
        max_idx = df["_row_idx"].max()
        recency_agg = (
            df.group_by(cid_col)
            .agg(pl.col("_row_idx").max().alias("_max_idx"))
            .with_columns(
                (pl.lit(max_idx) - pl.col("_max_idx")).cast(pl.Int32).alias("Recency")
            )
            .select([cid_col, "Recency"])
        )
        meta["recency_source"]   = "row-order proxy (no date column found)"
        meta["has_true_recency"] = False
        yield sse("step", {"stage": "recency", "title": "Recency estimated (no date column)",
            "detail": "Using row position as recency proxy", "warn": True})

    # ── Step 8: Build the RFM table ───────────────────────────────────────────
    # Join Recency, Frequency, and Monetary aggregations on CustomerID.
    rfm = (
        recency_agg
        .join(freq_agg,     on=cid_col, how="inner")
        .join(monetary_agg, on=cid_col, how="inner")
        .rename({cid_col: "CustomerID"})
    )
    n_customers = len(rfm)   # one row per unique customer
    rfm_preview = df_to_preview(rfm.select(["CustomerID", "Recency", "Frequency", "Monetary"]))

    # Compute descriptive stats for the report.
    rfm_stats = {col: {
        "min":    round(float(rfm[col].min()),    2),
        "max":    round(float(rfm[col].max()),    2),
        "mean":   round(float(rfm[col].mean()),   2),
        "median": round(float(rfm[col].median()), 2),
        "std":    round(float(rfm[col].std()),    2),
    } for col in ["Recency", "Frequency", "Monetary"]}

    yield sse("step", {"stage": "rfm", "title": "RFM table built",
        "detail": (f"{n_customers:,} customers · "
                   f"R {rfm['Recency'].mean():.0f}d avg · "
                   f"F {rfm['Frequency'].mean():.1f} avg · "
                   f"M ${rfm['Monetary'].mean():,.2f} avg")})

    # Cannot cluster fewer than 10 customers — abort early.
    if n_customers < 10:
        yield sse("error", {"message": f"Only {n_customers} unique customers — need ≥ 10."})
        return

    # ── Step 9: Scale features ────────────────────────────────────────────────
    # KMeans is sensitive to scale, so we:
    #   a) Apply log1p to compress heavy-tailed distributions (especially Monetary).
    #   b) Standardise with StandardScaler so each dimension has mean=0, std=1.
    rfm_vals = rfm.select(["Recency", "Frequency", "Monetary"]).to_numpy().astype(float)
    rfm_log  = np.log1p(rfm_vals)   # log1p(x) = log(1+x), safe for x=0
    scaler   = StandardScaler()
    scaled   = scaler.fit_transform(rfm_log)

    # Build a preview DataFrame of the scaled values for the report.
    rsc_df = pl.DataFrame({
        "CustomerID":       rfm["CustomerID"].to_list(),
        "Recency_scaled":   scaled[:, 0].tolist(),
        "Frequency_scaled": scaled[:, 1].tolist(),
        "Monetary_scaled":  scaled[:, 2].tolist(),
    })
    scaled_preview = df_to_preview(rsc_df)
    scaled_stats   = {col: {
        "min":  round(float(rsc_df[col].min()),  4),
        "max":  round(float(rsc_df[col].max()),  4),
        "mean": round(float(rsc_df[col].mean()), 4),
        "std":  round(float(rsc_df[col].std()),  4),
    } for col in ["Recency_scaled", "Frequency_scaled", "Monetary_scaled"]}

    yield sse("step", {"stage": "scale", "title": "Features log-transformed & standardized",
        "detail": "log1p → StandardScaler (mean=0, std=1)"})

    # ── Step 10: K-selection via silhouette score ─────────────────────────────
    # Test k values from 2 to min(8, n_customers-1) and pick the best.
    k_min, k_max = 2, min(8, n_customers - 1)

    # Use MiniBatchKMeans for large datasets (>2000 customers) — much faster,
    # slightly less accurate than full KMeans.
    Clusterer  = MiniBatchKMeans if n_customers > 2_000 else KMeans

    # For silhouette computation, sample up to 3000 points to limit runtime.
    sil_sample = min(n_customers, 3_000)
    sil_idx    = (np.random.choice(n_customers, sil_sample, replace=False)
                  if n_customers > sil_sample else None)
    sil_scaled = scaled[sil_idx] if sil_idx is not None else scaled

    sil_scores:   dict  = {}
    best_k_model        = None
    best_k_score: float = -1.0

    for k in range(k_min, k_max + 1):
        n_init   = 3 if Clusterer is MiniBatchKMeans else 5
        model    = Clusterer(n_clusters=k, n_init=n_init, random_state=42)
        labels_k = model.fit_predict(scaled)

        # Silhouette score: ranges from -1 (bad) to 1 (perfect separation).
        # Higher is better — measures how well each point fits its own cluster
        # versus the nearest neighbouring cluster.
        score = silhouette_score(
            sil_scaled, labels_k[sil_idx] if sil_idx is not None else labels_k
        )
        sil_scores[k] = round(float(score), 4)

        # Track the best model so we don't have to refit later.
        if score > best_k_score:
            best_k_score = score
            best_k_model = model

        yield sse("step", {
            "stage": f"k{k}", "title": f"Tested k={k}",
            "detail": f"Silhouette: {score:.4f}" +
                      (" ← best so far" if score == max(sil_scores.values()) else ""),
            "sil_scores": sil_scores.copy(),
        })

    best_k = max(sil_scores, key=sil_scores.get)   # k with the highest silhouette
    yield sse("step", {"stage": "best_k", "title": f"Best k = {best_k} selected",
        "detail": f"Silhouette score: {sil_scores[best_k]:.4f}",
        "sil_scores": sil_scores})

    # Retrieve the label array from the best-k model (already fitted above).
    labels = best_k_model.labels_

    # Persist cluster labels in the session so /recommend can filter by segment.
    if session_id:
        store_labels(session_id,
                     customer_ids=rfm["CustomerID"].to_list(),
                     labels=labels.tolist())

    # ── Step 11: Build cluster profiles ──────────────────────────────────────
    profiles: list = []
    for cid in sorted(set(labels)):
        mask = labels == cid           # boolean mask for this cluster
        r, f, m = rfm_vals[mask, 0], rfm_vals[mask, 1], rfm_vals[mask, 2]
        profiles.append({
            "cluster":          int(cid) + 1,            # 1-indexed for display
            "size":             int(mask.sum()),
            "pct_customers":    round(float(mask.sum()) / n_customers * 100, 1),
            "mean_recency":     round(float(r.mean()),       1),
            "mean_frequency":   round(float(f.mean()),       2),
            "mean_monetary":    round(float(m.mean()),       2),
            "median_recency":   round(float(np.median(r)),   1),
            "median_frequency": round(float(np.median(f)),   2),
            "median_monetary":  round(float(np.median(m)),   2),
        })

    # Sort by a composite value score (best customers first) before AI naming,
    # so the AI receives segments ordered from most to least valuable.
    for p in profiles:
        # Higher frequency and monetary + lower recency = better customer.
        p["_score"] = (1 / (p["mean_recency"] + 1)) * p["mean_frequency"] * p["mean_monetary"]
    profiles.sort(key=lambda x: x["_score"], reverse=True)

    # ── Step 12: AI-powered segment naming via Groq ───────────────────────────
    # Ask the LLM to assign a short, business-appropriate name to each cluster.
    # If the API call fails for any reason, fall back to generic label names.
    fallback_labels = [
        "Champions", "Loyal Customers", "Potential Loyalists", "At Risk",
        "Cannot Lose Them", "Hibernating", "Lost Customers", "New Customers",
    ]
    try:
        groq_client = get_groq()

        # Build a plain-text summary of each segment for the prompt.
        seg_lines = [
            f"Segment {i+1}: {p['size']:,} customers ({p['pct_customers']}%) | "
            f"Avg Recency={p['mean_recency']} {'days' if meta.get('has_true_recency') else 'proxy'} | "
            f"Avg Frequency={p['mean_frequency']} txns | Avg Monetary=${p['mean_monetary']:,.2f}"
            for i, p in enumerate(profiles)
        ]
        naming_prompt = (
            f"You are a CRM analyst. Below are {best_k} customer segments from an RFM analysis, "
            f"ordered from highest to lowest value.\n"
            "For each segment, provide a short business-appropriate name (2-4 words) "
            "and a one-sentence description.\n\n"
            + "\n".join(seg_lines)
            + '\n\nRespond ONLY with valid JSON — an array of objects with keys "name" and '
              '"description", one per segment in the same order.\n'
              "No markdown, no extra text, just the JSON array."
        )
        naming_res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": naming_prompt}],
            temperature=0.3,    # low temperature for consistent, business-like names
            max_tokens=400,
        )
        raw = naming_res.choices[0].message.content.strip()

        # Strip markdown code fences if the model wrapped the JSON in them.
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        ai_names = json.loads(raw)

        # Apply AI names and descriptions; fall back per-entry if index is missing.
        for i, p in enumerate(profiles):
            fb = fallback_labels[i] if i < len(fallback_labels) else f"Segment {i+1}"
            p["segment"]     = ai_names[i].get("name", fb) if i < len(ai_names) else fb
            p["description"] = ai_names[i].get("description", "") if i < len(ai_names) else ""
    except Exception:
        # Any error (API unavailable, JSON parse failure, etc.) → use fallback names.
        for i, p in enumerate(profiles):
            p["segment"]     = fallback_labels[i] if i < len(fallback_labels) else f"Segment {i+1}"
            p["description"] = ""

    # Remove the internal sort key before sending profiles to the client.
    for p in profiles:
        p.pop("_score", None)

    # Re-sort by cluster number (1, 2, 3, …) for consistent frontend display.
    profiles.sort(key=lambda x: x["cluster"])

    yield sse("step", {"stage": "profiles", "title": "Segments profiled & named",
        "detail": "  ·  ".join(f"{p['segment']} ({p['size']:,})" for p in profiles)})

    # ── Step 13: Emit the final 'done' event with all results ─────────────────
    # This is the largest payload — it includes everything the frontend needs
    # to render the full Segmentation and Report tabs.
    yield sse("done", {
        "total_customers":    n_customers,
        "total_transactions": total_rows,
        "best_k":             best_k,
        "silhouette_scores":  sil_scores,
        "profiles":           profiles,
        "columns_detected":   {k: v for k, v in col_map.items()},
        "meta":               meta,
        "report": {
            "raw_preview":         raw_preview,       # first 8 rows of uploaded file
            "cleaned_preview":     cleaned_preview,   # first 8 rows after cleaning
            "rfm_preview":         rfm_preview,       # first 8 rows of RFM table
            "scaled_preview":      scaled_preview,    # first 8 rows of scaled features
            "rfm_stats":           rfm_stats,         # min/max/mean/median/std per RFM column
            "scaled_stats":        scaled_stats,      # same for scaled columns
            "preprocessing_steps": preprocessing_steps,  # cleaning decisions log
            "rows_raw":            total_rows,
            "rows_cleaned":        len(df),
            "rows_dropped_total":  total_rows - len(df),
            "unique_customers":    n_customers,
        },
    })
