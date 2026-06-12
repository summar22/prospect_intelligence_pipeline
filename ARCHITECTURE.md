# Architecture Document

## Overview

The Prospect Intelligence Pipeline processes ~487 raw prospect records through five sequential stages, producing a clean, enriched, ranked dataset of ~55-60 unique companies.

```
raw_prospects.csv → Ingest → Resolve → Enrich → Score → Output
```

## Key Design Decisions

### 1. Entity Resolution: Union-Find on Two Keys

**Problem:** The same company appears under many names ("Northwind Logistics Partners Inc", "Northwind Logistics Co", "northwind logistics global inc") and sometimes different sub-domains.

**Approach:** Extract a "company key" (first two meaningful words after stripping suffixes like Inc/LLC/Group) and a "domain root" (domain minus TLD). Records sharing either key are unioned using a disjoint-set data structure, which handles transitive merges correctly.

**Why this over fuzzy matching:** Fuzzy string matching (Levenshtein, Jaro-Winkler) would require tuning a similarity threshold and risks false positives between unrelated companies with similar-length names. The two-key approach is deterministic, fast, and leverages the domain signal which is highly reliable. The tradeoff is that it might not catch companies whose names share no first-two-word prefix, but inspecting the dataset confirmed this covers all actual duplicates.

**What I'd do with more time:** Add TF-IDF or n-gram similarity as a second pass to catch edge cases, with a configurable threshold and human-review queue for borderline matches.

### 2. Enrichment: Async with Client-Side Rate Limiting

**Problem:** The API has ~80-650ms latency per call, 8 req/s rate limit, 12% transient failure rate, and 6% not-found rate.

**Approach:** `httpx.AsyncClient` with `asyncio.Semaphore(6)` limits concurrency to ~6 in-flight requests. At 80-650ms latency, this yields ~4-7 effective RPS — safely under the 8/s limit. Exponential backoff handles 429s (rate limit) and 500s (transient errors). After 3 failed retries, records go to a dead-letter queue.

**Why semaphore over token bucket:** A semaphore is simpler and sufficient here. The API's rate limit is per-second with a sliding window, and our concurrency limit naturally stays under it because each request takes at least 80ms. A true token bucket would be needed if latency were near-zero.

**What I'd do with more time:** Add circuit-breaker pattern (stop all requests if failure rate exceeds threshold), and expose enrichment progress via a webhook or status endpoint.

### 3. Idempotency: Two Layers

**Layer 1 — Input hash:** The orchestrator hashes the input CSV. If the hash matches the previous run and output exists, the entire pipeline is skipped.

**Layer 2 — SQLite enrichment cache:** Each entity's enrichment result is stored in SQLite. On re-run (or resume after interruption), already-enriched entities are loaded from cache instead of re-calling the API.

**Why SQLite:** Zero-config, file-based, works in Docker without external services. Perfect for a pipeline that runs as a batch job. If this were a production system handling concurrent runs, I'd use PostgreSQL.

### 4. Scoring: Weighted Multi-Signal Formula

The scoring formula assigns 0-100 points across seven signals:

| Signal | Weight | Rationale |
|---|---|---|
| Employee count | 20 | Mid-market (50-500) companies are the ideal B2B target |
| Revenue band | 20 | Higher revenue = more purchasing power |
| Last funding | 15 | Recent funding means active spend on new tools |
| Data completeness | 15 | Prospects we know more about are more actionable |
| Hiring now | 10 | Growth signal — hiring companies need solutions |
| Industry | 10 | Software/Finance/Healthcare are high-value B2B verticals |
| Tech signals | 10 | More signals = more data to personalize outreach |

**Why these weights:** Employee count and revenue are the strongest predictors of B2B deal size. Funding recency and hiring indicate timing. Data completeness penalizes unknowns — there's no point ranking a prospect highly if we can't even reach them.

**What I'd do with more time:** A/B test the weights against actual conversion data. Add configurable scoring profiles for different ICP definitions.

### 5. Data Cleaning: Explicit Over Clever

Each field has a dedicated cleaning function rather than a generic "clean all strings" approach. This is intentional — the failure modes differ per field:

- **Dates** have 6+ formats in the data; we try each explicitly rather than using dateutil's parser which can silently guess wrong
- **Employee counts** have ranges ("50-250"), approximations ("~42"), and junk ("twelve")
- **Countries** have 3-4 variants each that must map to standard codes
- **Emails** need structural validation (not just stripping whitespace)

## Tradeoffs

| Decision | Benefit | Cost |
|---|---|---|
| Union-Find for dedup | Fast, deterministic, no threshold tuning | Might miss exotic duplicate patterns |
| Async enrichment | ~5x faster than sequential | More complex error handling |
| SQLite for state | Zero external deps, works in Docker | Single-writer only, no concurrent runs |
| Pandas for CSV parsing | Handles quoted commas correctly | Heavier dependency than stdlib csv |

## What I Would Do With More Time

1. **Smarter entity resolution** — n-gram similarity as a second pass, with confidence scores
2. **Streaming pipeline** — process records in batches instead of loading all into memory
3. **Monitoring dashboard** — expose run stats via a small FastAPI endpoint
4. **Configuration profiles** — different scoring weights for different market segments
5. **Integration tests** — spin up the API in-process and test the full pipeline end-to-end
6. **Retry dead letters** — scheduled job to re-process failed enrichments
