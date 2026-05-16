"""
AI-powered endpoints: executive summary, action plan, conversational chat.

PURPOSE:
    All three endpoints take the already-computed segmentation results (profiles,
    summary stats, analysis data) and pass them as context to the Groq LLM.
    The LLM's response is streamed token-by-token back to the frontend via
    FastAPI's StreamingResponse so the UI can display text as it arrives.

DATA SOURCE:
    No database or file is read here.  All data is passed in the request body
    (JSON) by the frontend, which obtained it from the /process SSE stream.
    The original uploaded file (CSV/XLSX/XLS) has already been processed by
    main.py and clustering.py before any of these endpoints are called.

ENDPOINTS:
    POST /ai/summary      — 4-5 sentence executive briefing (prose)
    POST /ai/action-plan  — markdown table with one action row per segment
    POST /ai/chat         — conversational Q&A scoped to the segmentation data
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import get_groq, GROQ_MODEL

router = APIRouter(prefix="/ai", tags=["AI"])


# ── /ai/summary ───────────────────────────────────────────────────────────────

@router.post("/summary")
async def ai_summary(payload: dict):
    """
    Stream a 4-5 sentence executive briefing for the segmentation results.

    Input (from request body):
        profiles  — list of cluster profile dicts (from clustering.py 'done' event)
        meta      — pipeline metadata (e.g. has_true_recency flag)
        summary   — high-level stats (total_customers, total_revenue, best_k)
        analysis  — date range and other analysis results
    """
    profiles = payload.get("profiles", [])
    meta     = payload.get("meta", {})
    summary  = payload.get("summary", {})
    analysis = payload.get("analysis", {})

    if not profiles:
        raise HTTPException(status_code=400, detail="No profiles provided.")

    has_true_recency = meta.get("has_true_recency", True)

    # Build a date range string for the prompt if date data is available.
    date_range = ""
    if analysis.get("date_min") and analysis.get("date_max"):
        date_range = f" spanning {analysis['date_min']} to {analysis['date_max']}"

    # Format each segment as a single descriptive line for the prompt.
    seg_lines = [
        f"- {p['segment']}: {p['size']:,} customers ({p['pct_customers']}%) | "
        f"R={p['mean_recency']}{'d' if has_true_recency else ''} | "
        f"F={p['mean_frequency']} | M=${p['mean_monetary']:,.2f}"
        + (f" — {p['description']}" if p.get("description") else "")
        for p in profiles
    ]

    prompt = (
        "You are a senior data analyst presenting RFM segmentation results to a business owner.\n"
        "Write a concise executive briefing (2-3 sentences) summarising the key findings below.\n"
        "Focus on: what the data reveals, which segments deserve immediate attention, "
        "and one sharp strategic observation.\n"
        "Do NOT use bullet points. Write in flowing, confident prose.\n\n"
        f"Dataset: {summary.get('total_customers', 0):,} customers{date_range}. "
        f"Total revenue: ${summary.get('total_revenue', 0):,.2f}. "
        f"{summary.get('best_k', len(profiles))} segments identified.\n\n"
        "Segments:\n" + "\n".join(seg_lines)
    )

    def stream():
        """Generator that yields text chunks from the Groq streaming API."""
        try:
            client     = get_groq()
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=True,         # stream token-by-token
                temperature=0.45,    # moderate creativity for varied but professional prose
                max_tokens=300,
            )
            for chunk in completion:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta   # push each text fragment to the frontend immediately
        except HTTPException:
            raise
        except Exception as e:
            yield f"[Error: {str(e)}]"

    return StreamingResponse(stream(), media_type="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── /ai/action-plan ───────────────────────────────────────────────────────────

@router.post("/action-plan")
async def ai_action_plan(payload: dict):
    """
    Stream a markdown action-plan table, one row per customer segment.

    The LLM is instructed to return ONLY a markdown table (no preamble),
    making it easy for the frontend to render it directly.

    Input (from request body):
        profiles — list of cluster profile dicts
        meta     — pipeline metadata
        summary  — high-level stats
    """
    profiles = payload.get("profiles", [])
    meta     = payload.get("meta", {})
    summary  = payload.get("summary", {})

    if not profiles:
        raise HTTPException(status_code=400, detail="No segment profiles provided.")

    # Build one descriptive line per segment for the prompt context.
    seg_lines = [
        f"- {p['segment']} (Cluster {p['cluster']}): "
        f"{p['size']:,} customers ({p['pct_customers']}%) | "
        f"Avg Recency: {p['mean_recency']} {'days' if meta.get('has_true_recency') else 'proxy'} | "
        f"Avg Frequency: {p['mean_frequency']} txns | "
        f"Avg Monetary: ${p['mean_monetary']:,.2f}"
        for p in profiles
    ]

    prompt = (
        f"You are a senior CRM and marketing strategist. A business has run RFM customer "
        f"segmentation on {summary.get('total_customers', 'N/A'):,} customers "
        f"with ${summary.get('total_revenue', 0):,.2f} total revenue.\n\n"
        "Here are the customer segments identified:\n"
        + "\n".join(seg_lines) + "\n\n"
        "Produce a practical, actionable marketing action plan. "
        "For each segment output a row in this exact markdown table format:\n\n"
        "| Segment | Key Insight | Primary Action | Channel | Goal |\n"
        "|---|---|---|---|---|\n\n"
        "Rules:\n"
        "- Key Insight: one sharp sentence about what defines this segment behaviorally\n"
        "- Primary Action: the single most impactful thing to do RIGHT NOW\n"
        "- Channel: the best channel (email, SMS, push, ads, direct mail, etc.)\n"
        "- Goal: the business outcome this action drives\n"
        "- Be specific and practical. No generic advice.\n"
        "- Do not add any text before or after the table."
    )

    def stream():
        """Generator that streams the markdown table token-by-token."""
        try:
            client     = get_groq()
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                temperature=0.4,    # slightly lower temperature for structured output
                max_tokens=1200,    # enough for a full table with 8 segments
            )
            for chunk in completion:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except HTTPException:
            raise
        except Exception as e:
            yield f"\n\n[Error: {str(e)}]"

    return StreamingResponse(stream(), media_type="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── /ai/chat ──────────────────────────────────────────────────────────────────

@router.post("/chat")
async def ai_chat(payload: dict):
    """
    Conversational Q&A scoped strictly to the user's segmentation data.

    The system prompt injects the full segmentation context so the LLM can
    answer data-specific questions without needing access to the raw file.
    Up to the last 20 messages of conversation history are included so the
    model can refer back to earlier questions in the same session.

    Input (from request body):
        message  — the user's latest question (string)
        history  — list of prior {role, content} message dicts
        context  — dict containing profiles, meta, summary, analysis,
                   top_products_revenue, top_products_quantity,
                   monthly_trend, weekday_data
    """
    message = payload.get("message", "").strip()
    history = payload.get("history", [])
    context = payload.get("context", {})

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Unpack all context data passed by the frontend.
    profiles              = context.get("profiles", [])
    meta                  = context.get("meta", {})
    summary               = context.get("summary", {})
    analysis              = context.get("analysis", {})
    top_products_revenue  = context.get("top_products_revenue", [])
    top_products_quantity = context.get("top_products_quantity", [])
    monthly_trend         = context.get("monthly_trend", [])
    weekday_data          = context.get("weekday_data", [])
    has_true_recency      = meta.get("has_true_recency", True)

    # Format segment data as compact lines for the system prompt.
    seg_lines = [
        f"  - {p['segment']}: {p['size']:,} customers ({p['pct_customers']}%) | "
        f"R={p['mean_recency']} | F={p['mean_frequency']} | M=${p['mean_monetary']:,.2f}"
        for p in profiles
    ]

    # Build optional context sections — only include if data is available.
    date_range = ""
    if analysis.get("date_min") and analysis.get("date_max"):
        date_range = f"Date range: {analysis['date_min']} to {analysis['date_max']}"

    top_countries = ""
    if analysis.get("country_breakdown"):
        top_countries = "Top countries: " + ", ".join(
            f"{c['country']} ({c['pct']}%)" for c in analysis["country_breakdown"][:3]
        )

    products_section = ""
    if top_products_revenue:
        products_section += "Top products by revenue: " + ", ".join(
            f"{p['product']} (${p['revenue']:,.2f})" for p in top_products_revenue[:10]
        ) + "\n"
    if top_products_quantity:
        products_section += "Top products by quantity: " + ", ".join(
            f"{p['product']} ({p['quantity']:,} units)" for p in top_products_quantity[:10]
        ) + "\n"

    trend_section = ""
    if monthly_trend:
        # Include only the most recent 6 months to keep the prompt concise.
        trend_section = "Recent monthly revenue (last 6 months): " + ", ".join(
            f"{m['month']}: ${m['revenue']:,.0f}" for m in monthly_trend[-6:]
        ) + "\n"

    weekday_section = ""
    if weekday_data:
        best_day  = max(weekday_data, key=lambda x: x["revenue"])
        worst_day = min(weekday_data, key=lambda x: x["revenue"])
        weekday_section = (
            f"Best sales day: {best_day['weekday']} (${best_day['revenue']:,.0f}) | "
            f"Lowest sales day: {worst_day['weekday']} (${worst_day['revenue']:,.0f})\n"
        )

    # The system prompt defines the assistant's role, knowledge scope, and response style.
    system_prompt = (
    "You are a data analyst assistant embedded in an RFM customer segmentation tool.\n"
    "Your role is ONLY to answer questions about this specific customer dataset and RFM analysis.\n\n"

    "=== SCOPE: YOU CAN ANSWER ===\n"
    "- Customer segments and their characteristics (recency, frequency, monetary value)\n"
    "- Product performance, trends, and sales patterns\n"
    "- Geographic breakdowns and customer behavior insights\n"
    "- Clustering quality and segmentation methodology\n"
    "- Marketing recommendations based on segment data\n"
    "- Anything related about the provided data\n\n"

    "=== SCOPE: YOU MUST DECLINE ===\n"
    "If a question is about topics outside this dataset (finance, politics, general knowledge, "
    "coding, personal advice, etc.), respond: 'That question is outside my scope. I only analyze "
    "this customer segmentation data. Ask me about your segments, products, or customer behavior.'\n\n"

    "=== DATASET SUMMARY ===\n"
    f"Total customers: {summary.get('total_customers', 'N/A'):,}\n"
    f"Total transactions: {summary.get('total_transactions', 'N/A'):,}\n"
    f"Total revenue: ${summary.get('total_revenue', 0):,.2f}\n"
    f"Total orders: {summary.get('total_orders', 'N/A'):,}\n"
    f"{date_range}\n{top_countries}\n"
    f"Recency method: {'days since last purchase' if has_true_recency else 'row-order proxy (no date column)'}\n\n"
    f"=== CUSTOMER SEGMENTS ({len(profiles)} segments) ===\n"
    + "\n".join(seg_lines) + "\n\n"
    "=== CLUSTERING QUALITY ===\n"
    f"Best k: {summary.get('best_k', 'N/A')} | "
    f"Best silhouette score: {summary.get('best_silhouette', 'N/A')}\n\n"
    "=== PRODUCTS & TRENDS ===\n"
    f"{products_section}{trend_section}{weekday_section}\n"
    "=== RESPONSE STYLE ===\n"
    "- Answer in 2-4 sentences unless deeper explanation is clearly needed\n"
    "- Be direct and data-driven\n"
    "- If you lack data to answer, say 'I don't have data on that'\n"
    "- Never make up information or invent data points"
)

    # Limit conversation history to the last 20 messages to stay within token budget.
    trimmed = history[-20:] if len(history) > 20 else history

    # Assemble the full messages array: system context + conversation history + new question.
    messages = [{"role": "system", "content": system_prompt}]
    messages += trimmed
    messages.append({"role": "user", "content": message})

    def stream():
        """Generator that streams the assistant's reply token-by-token."""
        try:
            client     = get_groq()
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                stream=True,
                temperature=0.5,    # balanced between creativity and factual accuracy
                max_tokens=600,     # enough for a thorough but concise answer
            )
            for chunk in completion:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except HTTPException:
            raise
        except Exception as e:
            yield f"[Error: {str(e)}]"

    return StreamingResponse(stream(), media_type="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
