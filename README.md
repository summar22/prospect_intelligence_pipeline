# Prospect Intelligence Pipeline

A backend pipeline that ingests messy prospect CSV data, resolves duplicates, enriches records via an external API, scores them, and outputs a clean ranked dataset.

Built for the Banao Technologies candidate task.

## Quick Start

### Option 1: Docker Compose (recommended)

```bash
docker-compose up --build
```

This starts the mock enrichment API and runs the full pipeline. Output appears in `./output/`.

### Option 2: Run locally

**1. Start the mock enrichment API:**

```bash
cd mock_enrichment_api
pip install -r requirements.txt
uvicorn app:app --port 8900
```

**2. In a separate terminal, run the pipeline:**

```bash
pip install -r requirements.txt
python run_pipeline.py
```

### Re-running

The pipeline is idempotent. Running it again with the same input skips all work. To force a re-run:

```bash
python run_pipeline.py --force
```

Enrichment results are cached in SQLite, so even a forced re-run won't re-fetch already-enriched entities.

## Project Structure

```
Pipeline/
├── data/
│   └── raw_prospects.csv              # Input (untouched)
├── mock_enrichment_api/
│   ├── app.py                         # Mock third-party API
│   ├── requirements.txt
│   └── Dockerfile
├── pipeline/
│   ├── config.py                      # Central configuration
│   ├── models.py                      # Data models (dataclasses)
│   ├── ingestion.py                   # Stage 1: CSV → clean records
│   ├── entity_resolution.py           # Stage 2: Deduplicate
│   ├── enrichment.py                  # Stage 3: API enrichment
│   ├── scoring.py                     # Stage 4: Score & rank
│   ├── output.py                      # Stage 5: Write results
│   └── orchestrator.py                # Ties stages together
├── tests/
│   ├── test_ingestion.py
│   ├── test_entity_resolution.py
│   └── test_scoring.py
├── output/                            # Generated at runtime
│   ├── enriched_prospects.json        # Final ranked output
│   ├── dead_letter.json               # Failed enrichments
│   ├── run_summary.json               # Run statistics
│   └── merge_details.json             # Entity merge log
├── run_pipeline.py                    # Entrypoint
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── ARCHITECTURE.md
└── AI_USAGE_LOG.md
```

## Output Files

| File | Description |
|---|---|
| `enriched_prospects.json` | All prospects, ranked by score (highest first) |
| `dead_letter.json` | Records that failed enrichment after all retries |
| `run_summary.json` | Structured report with counts from every stage |
| `merge_details.json` | Which records were merged and why |

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design decisions and tradeoffs.
