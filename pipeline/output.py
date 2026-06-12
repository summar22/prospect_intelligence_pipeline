"""
Stage 5 — Output
==================
Writes the final pipeline output files:
  1. enriched_prospects.json  — ranked list of all prospects
  2. dead_letter.json         — records that failed enrichment
  3. run_summary.json         — structured run report
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pipeline.config import OUTPUT_DIR
from pipeline.models import EnrichedProspect

logger = logging.getLogger(__name__)


def write_output(
    prospects: list[EnrichedProspect],
    run_id: str,
    started_at: str,
    ingestion_stats: dict,
    resolution_stats: dict,
    enrichment_stats: dict,
) -> dict:
    """
    Write all output files and return the run summary dict.

    Parameters
    ----------
    prospects : list[EnrichedProspect]
        Scored and sorted prospects.
    run_id : str
        Unique identifier for this pipeline run.
    started_at : str
        ISO timestamp when the run started.
    ingestion_stats, resolution_stats, enrichment_stats : dict
        Stats collected from each stage.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    completed_at = datetime.now(timezone.utc).isoformat()

    # ── 1. Main output: ranked prospects ─────────────────────────────────────
    prospects_path = OUTPUT_DIR / "enriched_prospects.json"
    prospects_data = [p.to_dict() for p in prospects]
    prospects_path.write_text(
        json.dumps(prospects_data, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Wrote %d prospects to %s", len(prospects), prospects_path)

    # ── 1b. CSV output for easy Excel viewing ────────────────────────────────
    import csv
    csv_path = OUTPUT_DIR / "enriched_prospects.csv"
    if prospects_data:
        keys = prospects_data[0].keys()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(prospects_data)
        logger.info("Wrote %d prospects to %s", len(prospects), csv_path)

    # ── 2. Dead-letter queue ─────────────────────────────────────────────────
    dead_letter = [p.to_dict() for p in prospects if p.enrichment_status == "failed"]
    dead_letter_path = OUTPUT_DIR / "dead_letter.json"
    dead_letter_path.write_text(
        json.dumps(dead_letter, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Wrote %d dead-letter records to %s", len(dead_letter), dead_letter_path)

    # ── 3. Run summary ───────────────────────────────────────────────────────
    summary = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "stages": {
            "ingestion": ingestion_stats,
            "entity_resolution": {
                k: v for k, v in resolution_stats.items()
                if k != "merge_details"  # too verbose for summary
            },
            "enrichment": enrichment_stats,
        },
        "total_output_records": len(prospects),
        "score_range": {
            "min": prospects[-1].score if prospects else 0,
            "max": prospects[0].score if prospects else 0,
            "mean": round(sum(p.score for p in prospects) / len(prospects), 2) if prospects else 0,
        },
        "top_10_prospects": [
            {
                "rank": i + 1,
                "company": p.company_name,
                "domain": p.domain,
                "score": p.score,
                "enrichment_status": p.enrichment_status,
            }
            for i, p in enumerate(prospects[:10])
        ],
    }

    summary_path = OUTPUT_DIR / "run_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Wrote run summary to %s", summary_path)

    # Also write merge details separately for traceability
    merge_path = OUTPUT_DIR / "merge_details.json"
    merge_path.write_text(
        json.dumps(resolution_stats.get("merge_details", []), indent=2, default=str),
        encoding="utf-8",
    )

    return summary
