"""
Data Analysis computation — fast, no ML.

PURPOSE:
    Produces summary statistics and chart-ready data for the Analysis tab
    in the frontend.  No machine-learning is performed here; this module
    is intentionally lightweight so results can be streamed immediately
    while the slower clustering pipeline runs in the background.

DATA SOURCE:
    Receives a Polars DataFrame that was already parsed from the user-uploaded
    file (CSV/XLSX/XLS) by utils.read_file_fast() in main.py:/process.
    The DataFrame is passed in directly — this module never reads from disk.

OUTPUTS (returned as a dict):
    - Revenue summary (total revenue, orders, quantity)
    - Top N products by revenue and by quantity
    - Monthly revenue trend
    - Country breakdown with percentage share
    - Weekday breakdown (best/worst days for sales)
"""
import datetime
import polars as pl

from app.utils import to_float, parse_dates


def compute_analysis(
    df: pl.DataFrame,
    col_map: dict,
    top_n: int = 10,
    date_start: str | None = None,
    date_end:   str | None = None,
) -> dict:
    """
    Compute all analysis metrics for the given DataFrame.

    Parameters
    ----------
    df         : full parsed DataFrame from the user's uploaded file
    col_map    : canonical → actual column name mapping (from utils.resolve_columns)
    top_n      : how many top products to return in each ranking
    date_start : optional ISO date string 'YYYY-MM-DD' to filter from (inclusive)
    date_end   : optional ISO date string 'YYYY-MM-DD' to filter to (inclusive)
    """
    # Unpack column names from the resolved map (may be None if column not found).
    date_col    = col_map.get("date")
    product_col = col_map.get("product")
    country_col = col_map.get("country")
    qty_col     = col_map.get("quantity")
    price_col   = col_map.get("unit_price")
    total_col   = col_map.get("total_amount")
    inv_col     = col_map.get("invoice_no")

    # ── Revenue ──────────────────────────────────────────────────────────────
    # Build a unified '_revenue' column using the best available source.
    # Priority: pre-computed total > unit_price × quantity > quantity alone > 0.
    if total_col:
        df = to_float(df, total_col)
        df = df.with_columns(pl.col(total_col).fill_null(0.0).alias("_revenue"))
    elif qty_col and price_col:
        # Compute revenue by multiplying quantity × unit price.
        df = to_float(df, qty_col)
        df = to_float(df, price_col)
        df = df.with_columns(
            (pl.col(qty_col).fill_null(0.0) * pl.col(price_col).fill_null(0.0)).alias("_revenue")
        )
    elif qty_col:
        # Use quantity as a revenue proxy when price is unavailable.
        df = to_float(df, qty_col)
        df = df.with_columns(pl.col(qty_col).fill_null(0.0).alias("_revenue"))
    else:
        # No monetary info at all — set revenue to 0 (should not normally happen).
        df = df.with_columns(pl.lit(0.0).alias("_revenue"))

    # Build a '_qty' column used for quantity-based rankings.
    if qty_col:
        df = to_float(df, qty_col)
        df = df.with_columns(pl.col(qty_col).fill_null(0.0).alias("_qty"))
    else:
        # Fall back to revenue as quantity proxy.
        df = df.with_columns(pl.col("_revenue").alias("_qty"))

    # Drop rows with non-positive revenue (returns, cancellations, errors).
    df = df.filter(pl.col("_revenue") > 0)

    # ── Dates ─────────────────────────────────────────────────────────────────
    has_date = False
    date_min_str = date_max_str = None

    if date_col:
        df = parse_dates(df, date_col)             # normalise to pl.Date
        df = df.filter(pl.col(date_col).is_not_null())  # drop unparseable rows
        if len(df) > 0:
            has_date     = True
            date_min_str = str(df[date_col].min())
            date_max_str = str(df[date_col].max())

            # Apply optional date filters requested by the /analyze endpoint.
            if date_start:
                try:
                    ds = pl.lit(date_start).str.to_date().item()
                    df = df.filter(pl.col(date_col) >= ds)
                except Exception:
                    pass  # ignore invalid date strings

            if date_end:
                try:
                    # Add one day so the filter is inclusive of the end date.
                    de = pl.lit(date_end).str.to_date().item() + datetime.timedelta(days=1)
                    df = df.filter(pl.col(date_col) < de)
                except Exception:
                    pass

    # ── Summary stats ─────────────────────────────────────────────────────────
    total_revenue = round(float(df["_revenue"].sum()), 2)
    # Count unique invoices as 'orders'; fall back to row count if no invoice column.
    total_orders  = int(df[inv_col].n_unique()) if inv_col else len(df)
    total_qty     = int(df["_qty"].sum())

    # ── Top products ──────────────────────────────────────────────────────────
    top_products_rev: list = []
    top_products_qty: list = []
    if product_col:
        # Aggregate revenue and quantity per product, then take the top N.
        top_products_rev = (
            df.group_by(product_col)
            .agg(pl.col("_revenue").sum().round(2).alias("revenue"))
            .sort("revenue", descending=True)
            .head(top_n)
            .rename({product_col: "product"})
            .to_dicts()
        )
        top_products_qty = (
            df.group_by(product_col)
            .agg(pl.col("_qty").sum().cast(pl.Int64).alias("quantity"))
            .sort("quantity", descending=True)
            .head(top_n)
            .rename({product_col: "product"})
            .to_dicts()
        )

    # ── Monthly trend ─────────────────────────────────────────────────────────
    monthly_trend: list = []
    if has_date:
        # Format date as 'YYYY-MM' for grouping, then sort chronologically.
        monthly_trend = (
            df.with_columns(pl.col(date_col).dt.strftime("%Y-%m").alias("_month"))
            .group_by("_month")
            .agg(pl.col("_revenue").sum().round(2).alias("revenue"))
            .sort("_month")
            .rename({"_month": "month"})
            .to_dicts()
        )

    # ── Country breakdown ─────────────────────────────────────────────────────
    country_breakdown: list = []
    if country_col:
        ctry = (
            df.group_by(country_col)
            .agg(pl.col("_revenue").sum().round(2).alias("revenue"))
            .sort("revenue", descending=True)
            .head(15)   # limit to top 15 countries
            .rename({country_col: "country"})
        )
        total_ctry = ctry["revenue"].sum()
        # Append percentage share for each country.
        country_breakdown = (
            ctry.with_columns(
                (pl.col("revenue") / total_ctry * 100).round(1).alias("pct")
            )
            .to_dicts()
        )

    # ── Weekday breakdown ─────────────────────────────────────────────────────
    weekday_data: list = []
    if has_date:
        # Map day names to integers so we can sort Mon→Sun correctly.
        DAY_ORDER = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6,
        }
        weekday_data = (
            df.with_columns(pl.col(date_col).dt.strftime("%A").alias("_weekday"))
            .group_by("_weekday")
            .agg(pl.col("_revenue").sum().round(2).alias("revenue"))
            .rename({"_weekday": "weekday"})
            .with_columns(
                # Add a numeric sort key from the DAY_ORDER mapping.
                pl.col("weekday").replace(DAY_ORDER, return_dtype=pl.Int32).alias("_ord")
            )
            .sort("_ord")
            .drop("_ord")   # remove the helper column before returning
            .to_dicts()
        )

    return {
        "columns_detected":      {k: v for k, v in col_map.items()},
        "has_date":              has_date,
        "date_min":              date_min_str,
        "date_max":              date_max_str,
        "filtered_rows":         len(df),
        "summary": {
            "total_revenue": total_revenue,
            "total_orders":  total_orders,
            "total_qty":     total_qty,
        },
        "top_products_revenue":  top_products_rev,
        "top_products_quantity": top_products_qty,
        "monthly_trend":         monthly_trend,
        "country_breakdown":     country_breakdown,
        "weekday_data":          weekday_data,
    }
