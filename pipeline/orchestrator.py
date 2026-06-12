"""
Orchestrator
=============
Ties all pipeline stages together into a single runnable sequence
that is idempotent and resumable.

Design decisions
----------------
* Each stage is called sequentially because later stages depend on
  earlier ones.  However, *within* the enrichment stage, work is
  done concurrently.
* The SQLite database acts as a checkpoint store.  If the pipeline
  is interrupted during enrichment and re-started, already-enriched
  entities are skipped automatically.
* For full idempotency on re-run: if the output files already exist
  with the same input hash, we skip the entire run.  Otherwise, we
  re-run all stages (ingestion and resolution are fast; enrichment
  is the bottleneck and is itself resumable).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipeline.config import DB_PATH, OUTPUT_DIR, RAW_CSV_PATH
from pipeline.ingestion import ingest
from pipeline.entity_resolution import resolve_entities
from pipeline.enrichment import enrich_entities
from pipeline.scoring import score_all
from pipeline.output import write_output

logger = logging.getLogger(__name__)


def _input_hash() -> str:
    """Hash the raw CSV to detect changes between runs."""
    h = hashlib.sha256()
    with open(RAW_CSV_PATH, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _load_last_run_hash() -> str | None:
    """Check if we have a cached run for this input."""
    marker = OUTPUT_DIR / ".last_input_hash"
    if marker.exists():
        return marker.read_text().strip()
    return None


def _save_run_hash(h: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / ".last_input_hash").write_text(h)


def run_pipeline(force: bool = False) -> dict:
    """
    Execute the full pipeline.

    Parameters
    ----------
    force : bool
        If True, skip the idempotency check and re-run everything.
        The enrichment stage still uses its own cache, so already-
        enriched entities won't be re-fetched.

    Returns
    -------
    dict : the run summary
    """
    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(timezone.utc).isoformat()

    logger.info("=" * 60)
    logger.info("Pipeline run %s started at %s", run_id, started_at)
    logger.info("=" * 60)

    # ── Idempotency check ────────────────────────────────────────────────────
    current_hash = _input_hash()
    if not force:
        last_hash = _load_last_run_hash()
        if last_hash == current_hash:
            summary_path = OUTPUT_DIR / "run_summary.json"
            if summary_path.exists():
                logger.info(
                    "Input unchanged (hash=%s) and output exists. "
                    "Skipping run.  Use --force to re-run.",
                    current_hash,
                )
                return json.loads(summary_path.read_text())

    # ── Stage 1: Ingest & Normalize ──────────────────────────────────────────
    logger.info("─── Stage 1: Ingestion & Normalization ───")
    records, ingestion_stats = ingest()
    logger.info("  -> %d clean records", len(records))

    # ── Stage 2: Entity Resolution ───────────────────────────────────────────
    logger.info("─── Stage 2: Entity Resolution ───")
    entities, resolution_stats = resolve_entities(records)
    logger.info("  -> %d unique entities", len(entities))

    # ── Stage 3: Enrichment ──────────────────────────────────────────────────
    logger.info("─── Stage 3: Enrichment ───")
    enriched, enrichment_stats = enrich_entities(entities)
    logger.info("  -> %d enriched records", len(enriched))

    # ── Stage 4: Scoring ─────────────────────────────────────────────────────
    logger.info("─── Stage 4: Scoring ───")
    scored = score_all(enriched)
    logger.info("  -> scores computed and sorted")

    # ── Stage 5: Output ──────────────────────────────────────────────────────
    logger.info("─── Stage 5: Output ───")
    summary = write_output(
        prospects=scored,
        run_id=run_id,
        started_at=started_at,
        ingestion_stats=ingestion_stats,
        resolution_stats=resolution_stats,
        enrichment_stats=enrichment_stats,
    )

    _save_run_hash(current_hash)

    logger.info("=" * 60)
    logger.info("Pipeline run %s completed successfully!", run_id)
    logger.info("  Total records output: %d", summary["total_output_records"])
    logger.info("  Score range: %.1f - %.1f", summary["score_range"]["min"], summary["score_range"]["max"])
    logger.info("=" * 60)

    return summary
