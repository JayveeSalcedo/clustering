"""
RFMseg API — entry point.

Module layout
─────────────
app/config.py      Groq client + env loading
app/session.py     In-memory session cache (DataFrame + cluster labels)
app/utils.py       File reader, column resolver, Polars helpers, SSE formatter
app/analysis.py    compute_analysis() — fast stats, no ML
app/clustering.py  run_clustering()  — RFM pipeline + KMeans + AI naming
app/ai_routes.py   /ai/summary, /ai/action-plan, /ai/chat
app/recommend.py   /recommend — FP-Growth association rule mining

DATA SOURCE:
    All data originates from a user-uploaded file (CSV, XLSX, or XLS) sent via
    the /process or /analyze endpoints. The canonical sample dataset is:
      C:/Users/ACER/Desktop/dataset/Online Retail.xlsx
    Once uploaded, the parsed DataFrame is cached in memory (app/session.py)
    and referenced by a session_id for subsequent requests.
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from app.session   import cache_session, get_session
from app.utils     import read_file_fast, resolve_columns, sse
from app.analysis  import compute_analysis
from app.clustering import run_clustering
from app.ai_routes  import router as ai_router
from app.recommend  import router as rec_router

app = FastAPI(title="RFM Segmentation API")

# Allow all origins so the React frontend (any port/host) can reach this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the AI and recommendation sub-routers.
app.include_router(ai_router)
app.include_router(rec_router)


# ── /process ──────────────────────────────────────────────────────────────────

@app.post("/process")
async def process(file: UploadFile = File(...), top_n: int = Form(10)):
    """
    Main pipeline endpoint.

    Data flow:
      1. Browser uploads a CSV/XLSX/XLS file → bytes arrive here as `file`.
      2. read_file_fast() parses the bytes into a Polars DataFrame.
      3. resolve_columns() maps known aliases to the actual column names.
      4. cache_session() stores the DataFrame in memory and returns a session_id.
      5. compute_analysis() produces fast summary statistics (no ML).
      6. run_clustering() runs the full RFM + KMeans pipeline as a generator,
         streaming each intermediate result as an SSE event.

    The client (frontend) listens to the SSE stream and updates the UI
    incrementally as each event arrives.
    """
    # Read the raw bytes from the uploaded file.
    content = await file.read()
    fname   = file.filename or ""

    # Reject unsupported file formats early.
    if not fname.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only CSV or Excel files are supported.")

    # Parse bytes → Polars DataFrame using the appropriate reader.
    try:
        df = read_file_fast(content, fname)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    # Resolve actual column names from known aliases (e.g. "CustomerID", "customer_id", etc.)
    col_map = resolve_columns(df)

    # A customer ID column is mandatory for RFM to work.
    if "customer_id" not in col_map:
        raise HTTPException(status_code=400,
                            detail="Could not find a Customer ID / Name column.")
    # At least one monetary-value column must exist.
    if not any(k in col_map for k in ("total_amount", "unit_price", "quantity")):
        raise HTTPException(status_code=400,
                            detail="Could not find a monetary column.")

    # Store the DataFrame in memory so later endpoints can reuse it without re-upload.
    session_id = cache_session(df, col_map)

    def stream():
        # Immediately emit the analysis (summary stats) event so the UI can render
        # charts while the slower clustering pipeline is still running.
        analysis                = compute_analysis(df, col_map, top_n=top_n)
        analysis["session_id"]  = session_id
        yield sse("analysis", analysis)

        # Yield each clustering step as its own SSE event (see app/clustering.py).
        yield from run_clustering(df, col_map, session_id=session_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # Disable buffering so events are pushed to the client immediately.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /analyze ──────────────────────────────────────────────────────────────────

@app.post("/analyze")
async def analyze(
    session_id: str        = Form(None),
    date_start: str        = Form(None),
    date_end:   str        = Form(None),
    top_n:      int        = Form(10),
    file:       UploadFile = File(None),
):
    """
    Re-run analysis with updated date filters or top_n value.

    Data source priority:
      1. If a valid session_id exists, reuse the cached DataFrame from memory
         (no re-upload needed — the user's file is still held in app/session.py).
      2. If the session has expired (>30 min) or is absent, the caller must
         supply the file again as a fallback.
    """
    # Try to retrieve the cached DataFrame first.
    df, col_map = get_session(session_id) if session_id else (None, None)

    if df is None:
        # Session expired or not provided — require a fresh file upload.
        if file is None:
            raise HTTPException(status_code=400,
                                detail="Session expired. Please re-upload your file.")
        content = await file.read()
        fname   = file.filename or ""
        if not fname.lower().endswith((".csv", ".xlsx", ".xls")):
            raise HTTPException(status_code=400,
                                detail="Only CSV or Excel files are supported.")
        try:
            df = read_file_fast(content, fname)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read file: {e}")
        col_map = resolve_columns(df)

    # Re-compute analysis with the new filter parameters (date range / top_n).
    result               = compute_analysis(df, col_map, top_n=top_n,
                                            date_start=date_start, date_end=date_end)
    result["session_id"] = session_id
    return JSONResponse(result)


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Simple liveness check used by the frontend to verify the API is running."""
    return {"status": "ok"}
