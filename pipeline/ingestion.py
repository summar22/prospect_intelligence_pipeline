"""
Stage 1 — Ingestion & Normalization
====================================
Reads the raw CSV, cleans every field, and returns a list of
NormalizedProspect objects.  Rows that are fundamentally junk
(missing both company_name AND domain, or missing record_id)
are dropped and counted.

Design decisions
----------------
* We use pandas for reading because the CSV has quoted commas inside
  fields (e.g. ``"northwind,logistics"``).  Python's built-in csv
  module handles this too, but pandas gives us easy column access.
* Every cleaning function is a pure function so it's trivially testable.
* Date parsing tries several formats in priority order rather than
  using dateutil.parser which can silently guess wrong.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

import pandas as pd

from pipeline.config import RAW_CSV_PATH
from pipeline.models import NormalizedProspect

logger = logging.getLogger(__name__)

# ── Country normalization map ────────────────────────────────────────────────
_COUNTRY_MAP = {
    "us": "US", "usa": "US", "u.s.a.": "US", "united states": "US",
    "uk": "GB", "united kingdom": "GB",
    "de": "DE", "germany": "DE",
    "india": "IN", "in": "IN",
    "ca": "CA", "canada": "CA",
    "australia": "AU",
}

# Date formats to try, in order of specificity
_DATE_FORMATS = [
    "%Y-%m-%d",       # 2025-08-08
    "%Y/%m/%d",       # 2025/06/12
    "%d/%m/%Y",       # 19/06/2025
    "%m/%d/%Y",       # 11/01/2025
    "%d %b %Y",       # 6 Sep 2025
    "%d %B %Y",       # 6 September 2025
]

# Email validation regex (basic but sufficient)
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$")


# ── Field cleaning functions ─────────────────────────────────────────────────

def clean_company_name(raw: str | None) -> str | None:
    """Strip, remove embedded commas, normalise whitespace, title-case."""
    if not raw or not str(raw).strip():
        return None
    name = str(raw).strip()
    # Remove commas that appear due to CSV quoting artefacts
    name = name.replace(",", " ")
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    # Title-case for consistency
    name = name.title()
    return name if name else None


def clean_domain(raw: str | None) -> str | None:
    """Lowercase, strip protocol/www prefix, trailing slashes."""
    if not raw or not str(raw).strip():
        return None
    d = str(raw).strip().lower()
    for prefix in ("https://", "http://", "www."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.rstrip("/")
    # Must contain at least one dot to be a valid domain
    if "." not in d or not d:
        return None
    return d


def clean_industry(raw: str | None) -> str | None:
    """Strip and title-case."""
    if not raw or not str(raw).strip():
        return None
    return str(raw).strip().title()


def parse_employee_count(raw: str | None) -> int | None:
    """
    Parse the many employee_count formats into a single integer midpoint.

    Examples:
        "11-50"      -> 30
        "1000+"      -> 1000
        "~42"        -> 42
        "10 to 210"  -> 110
        "200-290"    -> 245
        "130"        -> 130
        "twelve"     -> None  (non-numeric junk)
        "5+"         -> 5
        "18+"        -> 18
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # Remove tilde/approx markers
    s = s.replace("~", "").strip()
    # Remove plus sign (treat "1000+" as 1000)
    s = s.replace("+", "").strip()

    # Try "X to Y" pattern
    m = re.match(r"^(\d+)\s+to\s+(\d+)$", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo + hi) // 2

    # Try "X-Y" range pattern (but not negative numbers)
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo + hi) // 2

    # Try plain integer
    m = re.match(r"^(\d+)$", s)
    if m:
        return int(m.group(1))

    # Non-numeric (e.g. "twelve")
    logger.debug("Could not parse employee_count: %r", raw)
    return None


def normalize_country(raw: str | None) -> str | None:
    """Map the various country representations to ISO-ish 2-letter codes."""
    if not raw or not str(raw).strip():
        return None
    key = str(raw).strip().lower()
    return _COUNTRY_MAP.get(key)


def clean_email(raw: str | None) -> str | None:
    """Strip, lowercase, validate basic structure."""
    if not raw or not str(raw).strip():
        return None
    email = str(raw).strip().lower()
    if _EMAIL_RE.match(email):
        return email
    return None


def parse_date(raw: str | None) -> str | None:
    """
    Try multiple date formats and return ISO 8601 (YYYY-MM-DD) or None.

    We attempt formats in a deliberate order.  Ambiguous dates like
    "5/2/2025" are tried as MM/DD/YYYY first (US convention, since
    many records use that), then DD/MM/YYYY.
    """
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            # Sanity check: year should be 2024-2026 for this dataset
            if 2024 <= dt.year <= 2026:
                return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    logger.debug("Could not parse date: %r", raw)
    return None


# ── Main ingestion function ──────────────────────────────────────────────────

def ingest(csv_path: str | None = None) -> tuple[list[NormalizedProspect], dict]:
    """
    Read the raw CSV and return cleaned records + ingestion stats.

    Returns
    -------
    records : list[NormalizedProspect]
        Clean records ready for entity resolution.
    stats : dict
        Counts of total rows, kept rows, and dropped rows (with reasons).
    """
    path = csv_path or str(RAW_CSV_PATH)
    logger.info("Reading CSV from %s", path)

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    total_rows = len(df)

    records: list[NormalizedProspect] = []
    dropped_no_id = 0
    dropped_empty = 0

    for _, row in df.iterrows():
        rid = str(row.get("record_id", "")).strip()
        if not rid:
            dropped_no_id += 1
            continue

        name = clean_company_name(row.get("company_name"))
        domain = clean_domain(row.get("domain"))

        # Drop truly junk rows: no name AND no domain
        if not name and not domain:
            dropped_empty += 1
            continue

        records.append(NormalizedProspect(
            record_id=rid,
            company_name=name or "",
            domain=domain,
            industry=clean_industry(row.get("industry")),
            employee_count=parse_employee_count(row.get("employee_count")),
            country=normalize_country(row.get("country")),
            contact_email=clean_email(row.get("contact_email")),
            source_captured_at=parse_date(row.get("source_captured_at")),
        ))

    stats = {
        "total_rows": total_rows,
        "records_kept": len(records),
        "dropped_no_id": dropped_no_id,
        "dropped_empty": dropped_empty,
    }
    logger.info(
        "Ingestion complete: %d rows -> %d records (%d dropped)",
        total_rows, len(records), dropped_no_id + dropped_empty,
    )
    return records, stats
