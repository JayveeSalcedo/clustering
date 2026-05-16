import os
import warnings
from dotenv import load_dotenv
from fastapi import HTTPException
from groq import Groq

# Load environment variables from the .env file located at backend/.env.
# Expected variable: GROQ_API_KEY=<your_key>
load_dotenv()

# Suppress non-critical library warnings (e.g. sklearn convergence hints).
warnings.filterwarnings("ignore")

# The Groq-hosted LLM used for all AI text generation in this project.
GROQ_MODEL = "llama-3.3-70b-versatile"

# Module-level singleton — created once and reused across all requests.
_groq_client: Groq | None = None


def get_groq() -> Groq:
    """
    Return a lazily-initialised Groq client.

    On the first call the GROQ_API_KEY is read from the environment.
    Subsequent calls return the already-created client directly.
    Raises HTTP 503 if the key is missing or still set to the placeholder value.
    """
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key or api_key == "your_groq_api_key_here":
            raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured.")
        _groq_client = Groq(api_key=api_key)
    return _groq_client
