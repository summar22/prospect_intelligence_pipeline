#!/usr/bin/env python3
"""
Prospect Intelligence Pipeline — Entrypoint
=============================================
Run the full pipeline from the command line.

Usage:
    python run_pipeline.py           # normal run (skips if already done)
    python run_pipeline.py --force   # force re-run, enrichment cache still used
"""

import argparse
import json
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Run the Prospect Intelligence Pipeline"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force re-run even if output already exists for this input",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Reduce noise from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    from pipeline.orchestrator import run_pipeline

    try:
        summary = run_pipeline(force=args.force)
        print("\n" + "=" * 60)
        print("RUN SUMMARY")
        print("=" * 60)
        print(json.dumps(summary, indent=2))
        print("=" * 60)
    except Exception:
        logging.getLogger(__name__).exception("Pipeline failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
