"""
Data models for the pipeline.

Plain dataclasses — no ORM, no heavy deps. Each struct maps to one
logical stage of the pipeline so you can trace exactly what data
flows where.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class NormalizedProspect:
    """Output of Stage 1 (Ingestion & Normalization)."""

    record_id: str
    company_name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    country: Optional[str] = None
    contact_email: Optional[str] = None
    source_captured_at: Optional[str] = None  # ISO 8601

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResolvedEntity:
    """Output of Stage 2 (Entity Resolution).

    Represents a single *company* after merging duplicate records.
    """

    entity_id: str                        # generated UUID
    company_name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    country: Optional[str] = None
    contact_email: Optional[str] = None
    source_captured_at: Optional[str] = None
    source_record_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnrichmentResult:
    """Raw response from the enrichment API (fields may be null)."""

    domain: Optional[str] = None
    employee_count: Optional[int] = None
    industry: Optional[str] = None
    founded_year: Optional[int] = None
    revenue_band: Optional[str] = None
    tech_signals: Optional[list[str]] = None
    hiring_now: Optional[bool] = None
    last_funding_months_ago: Optional[int] = None


@dataclass
class EnrichedProspect:
    """Output of Stage 3+4 (Enrichment + Scoring).

    Merges the resolved entity data with API-enriched data and a score.
    """

    entity_id: str
    company_name: str
    domain: Optional[str] = None
    # From entity resolution
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    country: Optional[str] = None
    contact_email: Optional[str] = None
    source_captured_at: Optional[str] = None
    source_record_ids: list[str] = field(default_factory=list)
    # From enrichment API
    enriched_employee_count: Optional[int] = None
    enriched_industry: Optional[str] = None
    founded_year: Optional[int] = None
    revenue_band: Optional[str] = None
    tech_signals: Optional[list[str]] = None
    hiring_now: Optional[bool] = None
    last_funding_months_ago: Optional[int] = None
    # Enrichment metadata
    enrichment_status: str = "pending"  # success | not_found | failed | no_domain
    # From scoring
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
