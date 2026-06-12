"""
Central configuration for the Prospect Intelligence Pipeline.

All tuneable knobs live here so they are easy to find and override
via environment variables when running inside Docker.
"""

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
RAW_CSV_PATH = DATA_DIR / "raw_prospects.csv"
DB_PATH = BASE_DIR / "pipeline_state.db"

# ── Enrichment API ───────────────────────────────────────────────────────────
ENRICHMENT_API_URL = os.environ.get(
    "ENRICHMENT_API_URL", "http://localhost:8900"
)
ENRICHMENT_ENDPOINT = f"{ENRICHMENT_API_URL}/enrich"

# ── Enrichment client tuning ─────────────────────────────────────────────────
MAX_CONCURRENT_REQUESTS = 6        # semaphore limit (API allows ~8/s)
MAX_RETRIES = 3                    # retries per record on transient errors
RETRY_BACKOFF_BASE = 0.5           # seconds; doubles each retry
RATE_LIMIT_BACKOFF = 1.0           # initial backoff on 429

# ── Scoring weights (must sum to 100) ────────────────────────────────────────
SCORING_WEIGHTS = {
    "employee_count": 20,
    "industry": 10,
    "revenue_band": 20,
    "hiring_now": 10,
    "last_funding_months_ago": 15,
    "tech_signals": 10,
    "data_completeness": 15,
}

# High-value B2B industries for scoring bonus
HIGH_VALUE_INDUSTRIES = {
    "Software", "Finance", "Healthcare", "Manufacturing", "Energy",
}
