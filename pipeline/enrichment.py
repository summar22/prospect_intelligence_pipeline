"""
Stage 3 — Enrichment Client
============================
Calls the mock enrichment API for each resolved entity, handling:
  - Rate limiting (429) with exponential backoff
  - Transient failures (500) with retries
  - Not-found (404) records
  - Partial responses (null fields)
  - Concurrent requests via asyncio + semaphore

Design decisions
----------------
* httpx.AsyncClient for concurrent HTTP — much faster than sequential
  requests given the 80-650ms latency per call.
* Client-side semaphore at 6 concurrent requests keeps us safely under
  the API's ~8 req/s limit while maximising throughput.
* SQLite tracks which entities are already enriched, so re-runs skip
  them (idempotency).
* Records that fail all retries go to a dead-letter list for later
  manual or automated pickup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path

import httpx

from pipeline.config import (
    DB_PATH,
    ENRICHMENT_ENDPOINT,
    MAX_CONCURRENT_REQUESTS,
    MAX_RETRIES,
    RATE_LIMIT_BACKOFF,
    RETRY_BACKOFF_BASE,
)
from pipeline.models import EnrichedProspect, ResolvedEntity

logger = logging.getLogger(__name__)


# ── SQLite state management (idempotency) ────────────────────────────────────

def _init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS enrichment_state (
            entity_id   TEXT PRIMARY KEY,
            status      TEXT NOT NULL,      -- success | not_found | failed | no_domain
            response    TEXT,               -- JSON blob of API response
            attempts    INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def _get_completed_ids(conn: sqlite3.Connection) -> set[str]:
    """Return entity_ids that have already been enriched (any terminal status)."""
    rows = conn.execute(
        "SELECT entity_id FROM enrichment_state WHERE status != 'pending'"
    ).fetchall()
    return {r[0] for r in rows}


def _save_result(
    conn: sqlite3.Connection,
    entity_id: str,
    status: str,
    response: dict | None,
    attempts: int,
):
    conn.execute(
        """
        INSERT INTO enrichment_state (entity_id, status, response, attempts)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
            status = excluded.status,
            response = excluded.response,
            attempts = excluded.attempts
        """,
        (entity_id, status, json.dumps(response) if response else None, attempts),
    )
    conn.commit()


# ── Single-entity enrichment with retries ────────────────────────────────────

async def _enrich_one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    entity: ResolvedEntity,
    conn: sqlite3.Connection,
) -> tuple[str, dict | None]:
    """
    Call the enrichment API for one entity, retrying on transient errors.

    Returns (status, response_dict_or_None).
    """
    if not entity.domain:
        _save_result(conn, entity.entity_id, "no_domain", None, 0)
        return "no_domain", None

    attempts = 0
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        attempts = attempt + 1
        async with semaphore:
            try:
                resp = await client.post(
                    ENRICHMENT_ENDPOINT,
                    json={"domain": entity.domain},
                    timeout=10.0,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    _save_result(conn, entity.entity_id, "success", data, attempts)
                    return "success", data

                elif resp.status_code == 404:
                    _save_result(conn, entity.entity_id, "not_found", None, attempts)
                    return "not_found", None

                elif resp.status_code == 422:
                    _save_result(conn, entity.entity_id, "no_domain", None, attempts)
                    return "no_domain", None

                elif resp.status_code == 429:
                    # Rate limited — back off exponentially
                    backoff = RATE_LIMIT_BACKOFF * (2 ** attempt)
                    logger.warning(
                        "Rate limited for %s, backing off %.1fs",
                        entity.domain, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                elif resp.status_code == 500:
                    # Transient failure — retry with backoff
                    backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "Transient error for %s (attempt %d/%d), retrying in %.1fs",
                        entity.domain, attempts, MAX_RETRIES + 1, backoff,
                    )
                    last_error = f"HTTP 500: {resp.text}"
                    await asyncio.sleep(backoff)
                    continue

                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    logger.error("Unexpected status for %s: %s", entity.domain, last_error)

            except httpx.RequestError as exc:
                last_error = str(exc)
                backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Request error for %s: %s, retrying in %.1fs",
                    entity.domain, exc, backoff,
                )
                await asyncio.sleep(backoff)
                continue

    # All retries exhausted -> dead letter
    logger.error(
        "Enrichment failed for %s after %d attempts: %s",
        entity.domain, attempts, last_error,
    )
    _save_result(conn, entity.entity_id, "failed", None, attempts)
    return "failed", None


# ── Batch enrichment ─────────────────────────────────────────────────────────

async def _enrich_batch(
    entities: list[ResolvedEntity],
    conn: sqlite3.Connection,
) -> list[EnrichedProspect]:
    """Enrich all entities concurrently, respecting rate limits."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    already_done = _get_completed_ids(conn)

    results: list[EnrichedProspect] = []

    async with httpx.AsyncClient() as client:
        tasks = []
        task_entities = []

        for entity in entities:
            if entity.entity_id in already_done:
                # Load cached result from DB
                row = conn.execute(
                    "SELECT status, response FROM enrichment_state WHERE entity_id = ?",
                    (entity.entity_id,),
                ).fetchone()
                if row:
                    status, resp_json = row
                    resp = json.loads(resp_json) if resp_json else None
                    results.append(_build_enriched(entity, status, resp))
                    continue

            tasks.append(_enrich_one(client, semaphore, entity, conn))
            task_entities.append(entity)

        if tasks:
            logger.info("Enriching %d entities (%d cached)...", len(tasks), len(results))
            outcomes = await asyncio.gather(*tasks)

            for entity, (status, resp) in zip(task_entities, outcomes):
                results.append(_build_enriched(entity, status, resp))

    return results


def _build_enriched(
    entity: ResolvedEntity,
    status: str,
    api_response: dict | None,
) -> EnrichedProspect:
    """Merge entity data with API response into an EnrichedProspect."""
    ep = EnrichedProspect(
        entity_id=entity.entity_id,
        company_name=entity.company_name,
        domain=entity.domain,
        industry=entity.industry,
        employee_count=entity.employee_count,
        country=entity.country,
        contact_email=entity.contact_email,
        source_captured_at=entity.source_captured_at,
        source_record_ids=entity.source_record_ids,
        enrichment_status=status,
    )

    if api_response:
        ep.enriched_employee_count = api_response.get("employee_count")
        ep.enriched_industry = api_response.get("industry")
        ep.founded_year = api_response.get("founded_year")
        ep.revenue_band = api_response.get("revenue_band")
        ep.tech_signals = api_response.get("tech_signals")
        ep.hiring_now = api_response.get("hiring_now")
        ep.last_funding_months_ago = api_response.get("last_funding_months_ago")

    return ep


# ── Public API (sync wrapper) ────────────────────────────────────────────────

def enrich_entities(
    entities: list[ResolvedEntity],
) -> tuple[list[EnrichedProspect], dict]:
    """
    Enrich all entities via the mock API.

    Returns
    -------
    enriched : list[EnrichedProspect]
    stats : dict  with enrichment counts
    """
    conn = _init_db(DB_PATH)

    try:
        enriched = asyncio.run(_enrich_batch(entities, conn))
    finally:
        conn.close()

    # Compute stats
    status_counts = {}
    for ep in enriched:
        status_counts[ep.enrichment_status] = (
            status_counts.get(ep.enrichment_status, 0) + 1
        )

    dead_letter = [ep for ep in enriched if ep.enrichment_status == "failed"]

    stats = {
        "total_entities": len(entities),
        "enrichment_success": status_counts.get("success", 0),
        "enrichment_not_found": status_counts.get("not_found", 0),
        "enrichment_failed": status_counts.get("failed", 0),
        "enrichment_no_domain": status_counts.get("no_domain", 0),
        "dead_letter_count": len(dead_letter),
    }
    logger.info("Enrichment complete: %s", stats)
    return enriched, stats
