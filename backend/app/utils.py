"""
Shared utilities: file reading, column resolution, Polars helpers, SSE formatter.

DATA SOURCE CONTEXT:
    read_file_fast() is the single entry point for converting the user-uploaded
    file bytes (CSV / XLSX / XLS) into a Polars DataFrame.  All other modules
    receive an already-parsed DataFrame; they never touch the raw bytes.

    The primary sample dataset used during development is:
      C:/Users/ACER/Desktop/dataset/Online Retail.xlsx
    but any similarly-structured transactional file is supported.
"""
import io
import json
import tempfile
import os
import polars as pl

# ── Column aliases ────────────────────────────────────────────────────────────
# Maps a canonical internal name to a list of real-world header spellings.
# resolve_columns() uses this to normalise whatever column names the user's
# file happens to have into the internal names the rest of the pipeline expects.
COLUMN_ALIASES: dict[str, list[str]] = {
    "customer_id": [
        "customerid", "customer_id", "custid", "client_id", "cust_id",
        "userid", "user_id", "customer_name", "customername",
        "client_name", "clientname", "name", "member_id", "memberid",
    ],
    "date": [
        "invoicedate", "date", "transaction_date", "order_date",
        "purchase_date", "transactiondate", "orderdate", "visit_date", "sale_date",
    ],
    "invoice_no": [
        "invoiceno", "invoice_no", "transactionid", "transaction_id",
        "orderid", "order_id", "invoice", "receipt_id", "txn_id", "trans_id",
    ],
    "total_amount": [
        "total_amount", "totalamount", "total_cost", "totalcost", "total",
        "sales", "revenue", "total_sales", "amount", "totalprice", "total_price",
        "total_spend", "spend", "gross_amount", "net_amount",
    ],
    "quantity": [
        "quantity", "qty", "units", "amount_qty", "item_quantity",
        "total_items", "totalitems", "items", "num_items", "no_items", "no_of_items",
    ],
    "unit_price": [
        "unitprice", "unit_price", "price", "price_per_unit",
        "itemprice", "item_price", "rate", "unit_cost",
    ],
    "product": [
        "description", "product", "product_name", "productname", "item", "item_name",
        "itemname", "product_description", "sku_name", "article_name",
        "goods_name", "commodity",
    ],
    "country": [
        "country", "region", "location", "market",
        "territory", "country_name", "countryname",
    ],
}


# ── File reading ──────────────────────────────────────────────────────────────

def read_file_fast(content: bytes, filename: str) -> pl.DataFrame:
    """
    Convert raw file bytes from the user's upload into a Polars DataFrame.

    Supported formats and their parsers:
      .csv  → pl.read_csv()  (fast, native Polars reader)
      .xlsx → pl.read_excel() with calamine engine; falls back to pandas+openpyxl
      .xls  → pandas read_excel() with xlrd, then converted to Polars

    The 'calamine' engine is preferred for .xlsx because it is much faster than
    openpyxl, but openpyxl is kept as a fallback for edge-case files.

    Parameters
    ----------
    content  : raw bytes from UploadFile.read()
    filename : original filename, used only to detect the extension
    """
    fname = filename.lower()

    if fname.endswith(".csv"):
        # Parse CSV directly from an in-memory buffer.
        # infer_schema_length=10_000 reads up to 10 k rows before deciding column types.
        return pl.read_csv(
            io.BytesIO(content),
            infer_schema_length=10_000,
            ignore_errors=True,                           # skip malformed rows
            null_values=["", "NA", "N/A", "null", "NULL"],
        )

    if fname.endswith(".xlsx"):
        # calamine requires a real file path, not a BytesIO buffer — write to a temp file.
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            return pl.read_excel(tmp_path, engine="calamine")
        except Exception:
            # Fallback: use pandas + openpyxl (slower but more compatible).
            import pandas as pd
            return pl.from_pandas(pd.read_excel(io.BytesIO(content), engine="openpyxl"))
        finally:
            os.unlink(tmp_path)   # always clean up the temp file

    if fname.endswith(".xls"):
        # Legacy .xls format requires xlrd; pandas handles it and we convert to Polars.
        import pandas as pd
        return pl.from_pandas(pd.read_excel(io.BytesIO(content), engine="xlrd"))

    raise ValueError("Unsupported file format")


# ── Column resolution ─────────────────────────────────────────────────────────

def resolve_columns(df: pl.DataFrame) -> dict:
    """
    Map canonical internal names to the actual column names in the DataFrame.

    Steps:
      1. Build a lookup of normalised column names (lowercase, spaces→underscores)
         pointing to the original column name as it appears in the DataFrame.
      2. For each canonical name (e.g. 'customer_id'), iterate its alias list
         until one matches a normalised column name.
      3. Store the *original* (un-normalised) column name in the result so it
         can be used directly with Polars.

    Example result for 'Online Retail.xlsx':
      {
        'customer_id': 'CustomerID',
        'date':        'InvoiceDate',
        'invoice_no':  'InvoiceNo',
        'unit_price':  'UnitPrice',
        'quantity':    'Quantity',
        'product':     'Description',
        'country':     'Country',
      }
    """
    # Normalised-name → original-name lookup built from the DataFrame's actual headers.
    lower_cols = {c.lower().strip().replace(" ", "_"): c for c in df.columns}

    resolved: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower().replace(" ", "_") in lower_cols:
                resolved[canonical] = lower_cols[alias.lower().replace(" ", "_")]
                break   # first match wins; stop checking other aliases
    return resolved


# ── Polars helpers ────────────────────────────────────────────────────────────

def to_float(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """
    Safely cast a column to Float64.

    - If the column is already numeric, a simple cast is used.
    - If the column is a string (e.g. "12.5"), strict=False converts what it can
      and fills unparseable values with 0.0 instead of raising an error.
    """
    numeric = (pl.Float32, pl.Float64, pl.Int8, pl.Int16, pl.Int32, pl.Int64,
               pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64)
    if df[col].dtype in numeric:
        return df.with_columns(pl.col(col).cast(pl.Float64).alias(col))
    return df.with_columns(
        pl.col(col).cast(pl.Float64, strict=False).fill_null(0.0).alias(col)
    )


def parse_dates(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """
    Robustly parse a string/mixed/datetime column into pl.Date.

    Handles date-only strings, datetime strings with time components,
    ISO 8601, AM/PM formats, and Polars native Date/Datetime types.
    Tries each format and accepts the first one that produces at least
    one non-null value.  Falls back to row-order proxy if nothing works.
    """
    # Already a plain Date — nothing to do.
    if df[col].dtype == pl.Date:
        return df

    # Already a Datetime variant — just cast to Date.
    if isinstance(df[col].dtype, pl.Datetime) or df[col].dtype in (
        pl.Datetime, pl.Datetime("us"), pl.Datetime("ms"), pl.Datetime("ns")
    ):
        return df.with_columns(pl.col(col).cast(pl.Date))

    # Date-only formats
    date_formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%d.%m.%Y",
        "%Y.%m.%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ]

    # Datetime formats (with time component) — parsed then cast to Date
    datetime_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%d/%m/%Y %I:%M %p",
        "%m/%d/%Y %I:%M %p",
    ]

    str_col = df.with_columns(pl.col(col).cast(pl.Utf8))[col]

    # Try date-only formats first
    for fmt in date_formats:
        try:
            parsed = str_col.str.to_date(fmt, strict=False)
            if parsed.drop_nulls().len() > 0:
                return df.with_columns(parsed.alias(col))
        except Exception:
            continue

    # Try datetime formats — parse then cast to Date
    for fmt in datetime_formats:
        try:
            parsed = str_col.str.to_datetime(fmt, strict=False).cast(pl.Date)
            if parsed.drop_nulls().len() > 0:
                return df.with_columns(parsed.alias(col))
        except Exception:
            continue

    # Last resort: let Polars infer the format automatically
    for try_fn in [
        lambda s: s.str.to_date(strict=False),
        lambda s: s.str.to_datetime(strict=False).cast(pl.Date),
    ]:
        try:
            parsed = try_fn(str_col)
            if parsed.drop_nulls().len() > 0:
                return df.with_columns(parsed.alias(col))
        except Exception:
            continue

    return df   # give up — downstream will use row-order proxy


def df_to_preview(df: pl.DataFrame, n: int = 8) -> dict:
    """
    Serialize the first `n` rows of a DataFrame into a JSON-safe dict.

    All columns are cast to Utf8 (string) so the result can be safely
    serialised to JSON regardless of original dtypes.  Used by clustering.py
    to send table previews to the frontend via SSE.
    """
    sample = df.head(n).with_columns([
        pl.col(c).cast(pl.Utf8) for c in df.columns
    ])
    return {
        "columns":    list(sample.columns),
        "rows":       sample.fill_null("").rows(),
        "total_rows": len(df),
        "total_cols": len(df.columns),
    }


# ── SSE formatter ─────────────────────────────────────────────────────────────

def sse(event: str, data: dict) -> str:
    """
    Format a dict as a Server-Sent Events (SSE) message string.

    The browser's EventSource API parses messages in this format:
      event: <event_name>\\n
      data: <json_string>\\n
      \\n
    The double newline signals the end of one event.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
