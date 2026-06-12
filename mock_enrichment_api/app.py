"""
Mock Enrichment API
===================
A deliberately imperfect external service. It mimics a real third-party data
provider so the pipeline must handle the messy reality of calling one:

  - Rate limiting        -> 429 if you exceed ~8 requests/second
  - Transient failures   -> ~12% of calls return 500 (retrying usually works)
  - Variable latency     -> each call sleeps 80-650ms
  - Unknown records      -> 404 when a domain isn't in the dataset
  - Occasional partial   -> some records come back with fields missing

Run it:
    pip install -r requirements.txt
    uvicorn app:app --port 8900

Then POST to http://localhost:8900/enrich  with JSON: {"domain": "quillsoftware.com"}

Nothing here is real data. Everything is generated at startup from the domain.
"""

import hashlib
import random
import time
from collections import deque

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="Mock Enrichment API", version="1.0")

# ── config knobs (candidates may read these; they are part of the challenge) ──
RATE_LIMIT_PER_SEC = 8
TRANSIENT_FAILURE_RATE = 0.12
NOT_FOUND_RATE = 0.06          # some domains simply have no enrichment record
PARTIAL_RECORD_RATE = 0.15     # some records come back incomplete
MIN_LATENCY_S = 0.08
MAX_LATENCY_S = 0.65

INDUSTRIES = ["Logistics", "Software", "Retail", "Manufacturing", "Healthcare",
              "Finance", "Media", "Energy", "Education", "Telecom", "Insurance",
              "Pharmaceuticals", "Hospitality", "Gaming", "Construction"]
REVENUE_BANDS = ["<$1M", "$1M-$10M", "$10M-$50M", "$50M-$250M", "$250M+"]
TECH_POOL = ["aws", "gcp", "azure", "salesforce", "hubspot", "snowflake",
             "kubernetes", "react", "python", "stripe", "segment", "datadog"]

# token-bucket-ish limiter: timestamps of recent requests per client host
_request_log = {}


def _normalize_domain(raw: str) -> str:
    d = (raw or "").strip().lower()
    for prefix in ("https://", "http://", "www."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.rstrip("/")


def _deterministic_record(domain: str):
    """Generate a stable enrichment record from the domain hash."""
    h = int(hashlib.sha256(domain.encode()).hexdigest(), 16)
    rng = random.Random(h)
    record = {
        "domain": domain,
        "employee_count": rng.choice([8, 24, 60, 140, 320, 750, 1500, 4200]),
        "industry": rng.choice(INDUSTRIES),
        "founded_year": rng.randint(1985, 2024),
        "revenue_band": rng.choice(REVENUE_BANDS),
        "tech_signals": rng.sample(TECH_POOL, rng.randint(0, 4)),
        "hiring_now": rng.random() < 0.4,
        "last_funding_months_ago": rng.choice([None, 3, 7, 14, 26, None]),
    }
    return record


class EnrichRequest(BaseModel):
    domain: str | None = None
    company_name: str | None = None


@app.post("/enrich")
def enrich(req: EnrichRequest, request: Request):
    client = request.client.host if request.client else "unknown"

    # ── rate limiting (per client, sliding 1s window) ─────────────────────────
    now = time.monotonic()
    log = _request_log.setdefault(client, deque())
    while log and now - log[0] > 1.0:
        log.popleft()
    if len(log) >= RATE_LIMIT_PER_SEC:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Max ~8 req/s. Back off and retry.",
        )
    log.append(now)

    # ── latency ──────────────────────────────────────────────────────────────
    time.sleep(random.uniform(MIN_LATENCY_S, MAX_LATENCY_S))

    # ── transient failure (retrying usually succeeds) ─────────────────────────
    if random.random() < TRANSIENT_FAILURE_RATE:
        raise HTTPException(status_code=500, detail="Upstream provider error. Transient.")

    domain = _normalize_domain(req.domain or "")
    if not domain and req.company_name:
        # the provider can't resolve by name alone — force candidates to clean domains
        raise HTTPException(status_code=422, detail="A resolvable domain is required.")
    if not domain:
        raise HTTPException(status_code=422, detail="No domain provided.")

    # ── not found (no record exists for this domain) ──────────────────────────
    seed = int(hashlib.sha256(("nf" + domain).encode()).hexdigest(), 16) % 100
    if seed < NOT_FOUND_RATE * 100:
        raise HTTPException(status_code=404, detail=f"No enrichment record for {domain}.")

    record = _deterministic_record(domain)

    # ── partial record (some fields intentionally dropped) ────────────────────
    if random.random() < PARTIAL_RECORD_RATE:
        for field in random.sample(
            ["industry", "revenue_band", "founded_year", "tech_signals"],
            random.randint(1, 2),
        ):
            record[field] = None

    return record


@app.get("/health")
def health():
    return {"status": "ok"}
