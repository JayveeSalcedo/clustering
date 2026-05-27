"""
Product recommendation engine using association rule mining (FP-Growth).

PURPOSE:
    Discovers which products are frequently bought together (market-basket
    analysis) and returns the strongest association rules ranked by lift.
    Supports two modes:
      - Global: all customers in the uploaded dataset
      - Per-segment: only customers assigned to a specific KMeans cluster

DATA SOURCE:
    The raw transactional DataFrame is retrieved from the in-memory session
    cache (app/session.py) using the session_id supplied by the frontend.
    The data was originally parsed from the user-uploaded file
    (CSV/XLSX/XLS, e.g. 'Online Retail.xlsx') by utils.read_file_fast().
    Cluster labels (also in the session cache) are used to filter the
    DataFrame when a specific segment is requested.

ENDPOINT:
    POST /recommend
    Body (JSON): {
        session_id     : str   — identifies the cached DataFrame
        cluster_id     : int | null — 1-indexed cluster; null = all customers
        min_support    : float — minimum item-set support (default 0.02)
        min_confidence : float — minimum rule confidence (default 0.2)
        top_n          : int   — max rules to return, sorted by lift (default 30)
        profiles       : list  — segment profiles for resolving segment name
    }
"""
import polars as pl
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.session import get_session, get_labels

router = APIRouter(tags=["Recommendations"])


@router.post("/recommend")
async def recommend(payload: dict):
    # Import here to avoid slowing down startup — mlxtend is only needed for this endpoint.
    from mlxtend.frequent_patterns import fpgrowth, association_rules

    # ── Parse request parameters ──────────────────────────────────────────────
    session_id     = payload.get("session_id")
    cluster_id     = payload.get("cluster_id", None)     # None = all customers
    min_support    = float(payload.get("min_support",    0.02))
    min_confidence = float(payload.get("min_confidence", 0.2))
    top_n          = int(payload.get("top_n",            30))
    profiles       = payload.get("profiles", [])          # used to resolve segment name

    # Clamp thresholds to safe ranges to prevent degenerate results.
    min_support    = max(0.001, min(0.5,  min_support))
    min_confidence = max(0.05,  min(0.99, min_confidence))

    # ── Retrieve cached DataFrame from session ────────────────────────────────
    # Data lives in memory (app/session.py); originally from user-uploaded file.
    df, col_map = get_session(session_id) if session_id else (None, None)
    if df is None:
        raise HTTPException(
            status_code=400,
            detail="Session not found or expired. Please re-upload your file.",
        )

    # Resolve the actual column names from the canonical map.
    inv_col     = col_map.get("invoice_no")
    product_col = col_map.get("product")
    cid_col     = col_map.get("customer_id")

    # Both invoice and product columns are required for market-basket analysis.
    if not inv_col:
        raise HTTPException(status_code=422, detail="no_invoice")
    if not product_col:
        raise HTTPException(status_code=422, detail="no_product")

    # ── Optionally filter to a single customer segment ────────────────────────
    segment_name: str | None = None
    if cluster_id is not None:
        # Retrieve the cluster label assignments stored after clustering.
        cust_ids, labels = get_labels(session_id)
        if cust_ids is None:
            raise HTTPException(
                status_code=400,
                detail="Clustering not yet complete. Please wait for segmentation to finish.",
            )
        # cluster_id from the frontend is 1-indexed; KMeans labels are 0-indexed.
        target_label = int(cluster_id) - 1
        # Build a set of CustomerIDs that belong to this cluster for fast lookup.
        member_ids = {
            cid for cid, lbl in zip(cust_ids, labels) if lbl == target_label
        }
        # Find the human-readable segment name from the profiles list.
        for p in profiles:
            if p.get("cluster") == int(cluster_id):
                segment_name = p.get("segment", f"Cluster {cluster_id}")
                break
        # Keep only rows whose CustomerID is in this segment.
        working_df = df.filter(
            pl.col(cid_col).cast(pl.Utf8).str.strip_chars().is_in(member_ids)
        )
    else:
        # No filter — use all transactions across all customers.
        working_df = df

    # ── Clean product and invoice columns ─────────────────────────────────────
    # Drop nulls and blank strings; strip whitespace from both columns.
    working_df = (
        working_df
        .filter(pl.col(inv_col).is_not_null() & pl.col(product_col).is_not_null())
        .with_columns(
            pl.col(product_col).cast(pl.Utf8).str.strip_chars().alias(product_col),
            pl.col(inv_col).cast(pl.Utf8).str.strip_chars().alias(inv_col),
        )
        .filter((pl.col(product_col) != "") & (pl.col(inv_col) != ""))
    )

    n_transactions = working_df[inv_col].n_unique()
    n_products     = working_df[product_col].n_unique()

    # Require a minimum dataset size for meaningful association rules.
    if n_transactions < 10:
        raise HTTPException(status_code=422, detail="not_enough_transactions")
    if n_products < 2:
        raise HTTPException(status_code=422, detail="not_enough_products")

    # ── Build the basket matrix (invoice × product, boolean) ──────────────────
    # Each row = one invoice; each column = one product; True = product was purchased.
    # This is the standard "one-hot" format expected by mlxtend's fpgrowth().
    basket = (
        working_df
        .select([inv_col, product_col])
        .unique()                                    # deduplicate (invoice, product) pairs
        .with_columns(pl.lit(True).alias("_present"))
        .pivot(index=inv_col, on=product_col, values="_present")
        .fill_null(False)                            # False = product not in this invoice
    )
    # Convert to pandas bool DataFrame as required by mlxtend.
    basket_pd = basket.drop(inv_col).to_pandas().astype(bool)

    # ── FP-Growth: find frequent item sets ────────────────────────────────────
    # FP-Growth is more memory-efficient than Apriori for sparse datasets.
    # min_support = minimum fraction of transactions an item set must appear in.
    try:
        frequent_items = fpgrowth(basket_pd, min_support=min_support, use_colnames=True)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"mining_failed: {e}")

    # If no item sets meet the support threshold, return an empty result.
    if frequent_items.empty:
        return JSONResponse({
            "rules": [], "n_transactions": n_transactions, "n_products": n_products,
            "segment_name": segment_name, "empty_reason": "support_too_high",
            "process_log": [
                {"step": "Session retrieval", "status": "ok", "detail": f"{len(df):,} rows loaded"},
                {"step": "Column detection",  "status": "ok", "detail": f"Invoice: '{inv_col}' · Product: '{product_col}'"},
                {"step": "Segment filter",    "status": "ok" if cluster_id else "skip", "detail": f"Cluster {cluster_id}" if cluster_id else "All customers"},
                {"step": "Basket matrix",     "status": "ok", "detail": f"{n_transactions:,} invoices × {n_products:,} products"},
                {"step": "FP-Growth mining",  "status": "warn", "detail": f"No frequent item sets at min_support={min_support} — try lowering the Popularity slider"},
            ],
            "params": {"min_support": min_support, "min_confidence": min_confidence, "top_n": top_n},
        })

    # ── Derive association rules from frequent item sets ─────────────────────
    # confidence(A→B) = P(A∪B) / P(A)   — how often B follows A
    # lift(A→B)       = confidence / P(B) — improvement over random chance (>1 = useful)
    try:
        rules = association_rules(
            frequent_items,
            metric="confidence",
            min_threshold=min_confidence,
            num_itemsets=len(frequent_items),  # required by newer mlxtend versions
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"rules_failed: {e}")

    if rules.empty:
        return JSONResponse({
            "rules": [], "n_transactions": n_transactions, "n_products": n_products,
            "segment_name": segment_name, "empty_reason": "confidence_too_high",
            "process_log": [
                {
                    "step": "Session retrieval",
                    "status": "ok",
                    "detail": f"Loaded DataFrame from session cache · {len(df):,} rows · {len(df.columns)} columns",
                },
                {
                    "step": "Column detection",
                    "status": "ok",
                    "detail": f"Invoice column: '{inv_col}' · Product column: '{product_col}'"
                              + (f" · Customer column: '{cid_col}'" if cid_col else " · No customer column"),
                },
                {
                    "step": "Segment filter",
                    "status": "ok" if cluster_id is not None else "skip",
                    "detail": (
                        f"Filtered to segment '{segment_name}' (cluster {cluster_id}) · {len(member_ids):,} matching customers · {len(working_df):,} rows retained"
                        if cluster_id is not None
                        else "No segment filter applied — using all customers"
                    ),
                },
                {
                    "step": "Data cleaning",
                    "status": "ok",
                    "detail": f"Dropped null/blank invoice and product rows · {len(working_df):,} clean rows remaining",
                },
                {
                    "step": "Basket matrix",
                    "status": "ok",
                    "detail": f"{n_transactions:,} invoices × {n_products:,} products · "
                              f"Sparsity: {100 * (1 - basket_pd.sum().sum() / (basket_pd.shape[0] * basket_pd.shape[1])):.1f}% empty cells",
                },
                {
                    "step": "FP-Growth mining",
                    "status": "ok",
                    "detail": f"min_support={min_support} ({min_support*100:.1f}%) · "
                              f"{len(frequent_items):,} frequent item sets found",
                },
                {
                    "step": "Association rules",
                    "status": "warn",
                    "detail": f"No rules met min_confidence={min_confidence} ({min_confidence*100:.0f}%) — try lowering the Reliability slider",
                },
            ],
            "params": {
                "min_support":    min_support,
                "min_confidence": min_confidence,
                "top_n":          top_n,
                "cluster_id":     cluster_id,
                "segment_name":   segment_name,
                "n_frequent_items": len(frequent_items),
                "n_rules_before_limit": len(rules),
            },
        })

    # ── Sort by lift and return the top-N rules ───────────────────────────────
    # Lift > 1 means the two items are positively correlated.
    # Higher lift = stronger, more actionable recommendation.
    rules = rules.sort_values("lift", ascending=False).head(top_n)
    rules_out = [
        {
            "antecedents": sorted(list(row["antecedents"])),   # items already in cart
            "consequents": sorted(list(row["consequents"])),   # recommended items
            "support":     round(float(row["support"]),    4),
            "confidence":  round(float(row["confidence"]), 4),
            "lift":        round(float(row["lift"]),       4),
        }
        for _, row in rules.iterrows()
    ]

    # ── Build process log for frontend display ─────────────────────────────
    process_log = [
        {
            "step":   "Session retrieval",
            "status": "ok",
            "detail": f"Loaded DataFrame from session cache · {len(df):,} rows · {len(df.columns)} columns",
        },
        {
            "step":   "Column detection",
            "status": "ok",
            "detail": f"Invoice column: '{inv_col}' · Product column: '{product_col}'"
                      + (f" · Customer column: '{cid_col}'" if cid_col else " · No customer column"),
        },
        {
            "step":   "Segment filter",
            "status": "ok" if cluster_id is not None else "skip",
            "detail": (
                f"Filtered to segment '{segment_name}' (cluster {cluster_id}) · {len(member_ids):,} matching customers · {len(working_df):,} rows retained"
                if cluster_id is not None
                else "No segment filter applied — using all customers"
            ),
        },
        {
            "step":   "Data cleaning",
            "status": "ok",
            "detail": f"Dropped null/blank invoice and product rows · {len(working_df):,} clean rows remaining",
        },
        {
            "step":   "Basket matrix",
            "status": "ok",
            "detail": f"{n_transactions:,} invoices × {n_products:,} products · "
                      f"Sparsity: {100 * (1 - basket_pd.sum().sum() / (basket_pd.shape[0] * basket_pd.shape[1])):.1f}% empty cells",
        },
        {
            "step":   "FP-Growth mining",
            "status": "ok",
            "detail": f"min_support={min_support} ({min_support*100:.1f}%) · "
                      f"{len(frequent_items):,} frequent item sets found",
        },
        {
            "step":   "Association rules",
            "status": "ok",
            "detail": f"min_confidence={min_confidence} ({min_confidence*100:.0f}%) · "
                      f"{len(rules):,} rules generated · sorted by lift · top {top_n} returned",
        },
        {
            "step":   "Rule quality",
            "status": "ok",
            "detail": f"Avg lift: {rules['lift'].mean():.4f} · "
                      f"Max lift: {rules['lift'].max():.4f} · "
                      f"Avg confidence: {rules['confidence'].mean():.4f} · "
                      f"All rules lift > 1: {bool((rules['lift'] > 1).all())}",
        },
    ]

    return JSONResponse({
        "rules":          rules_out,
        "n_transactions": n_transactions,
        "n_products":     n_products,
        "segment_name":   segment_name,
        "empty_reason":   None,
        "process_log":    process_log,
        "params": {
            "min_support":    min_support,
            "min_confidence": min_confidence,
            "top_n":          top_n,
            "cluster_id":     cluster_id,
            "segment_name":   segment_name,
            "n_frequent_items": len(frequent_items),
            "n_rules_before_limit": len(rules),
        },
    })
