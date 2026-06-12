"""
Stage 4 — Scoring
==================
Assigns each enriched prospect a score on a 0-100 scale so the
final output can be ranked.

Scoring philosophy
------------------
We're modelling "how promising is this prospect for B2B outreach?"

* **Mid-market companies (50-500 employees)** are the sweet spot: large
  enough to have budget, small enough to be reachable.
* **Revenue band** directly indicates purchasing power.
* **Hiring now** signals growth and active spend.
* **Recent funding** means fresh capital and new initiatives.
* **Tech signals** indicate sophistication and potential fit.
* **Data completeness** penalises records we know little about — a
  prospect we can't even enrich is inherently lower priority.

Weight allocation (total = 100):
    employee_count:         20
    industry:               10
    revenue_band:           20
    hiring_now:             10
    last_funding_months_ago:15
    tech_signals:           10
    data_completeness:      15
"""

from __future__ import annotations

import logging

from pipeline.config import HIGH_VALUE_INDUSTRIES, SCORING_WEIGHTS
from pipeline.models import EnrichedProspect

logger = logging.getLogger(__name__)

# Revenue band ordering (higher = better prospect)
_REVENUE_SCORES = {
    "<$1M": 0.1,
    "$1M-$10M": 0.35,
    "$10M-$50M": 0.6,
    "$50M-$250M": 0.85,
    "$250M+": 1.0,
}


def _score_employee_count(emp: int | None) -> float:
    """
    0-1 score. Sweet spot is 50-500 (returns 1.0).
    Under 10 or over 5000 gets a low score.
    """
    if emp is None:
        return 0.3  # neutral — we simply don't know
    if 50 <= emp <= 500:
        return 1.0
    elif 10 <= emp < 50:
        return 0.6
    elif 500 < emp <= 1500:
        return 0.7
    elif 1500 < emp <= 5000:
        return 0.4
    elif emp > 5000:
        return 0.2
    else:  # < 10
        return 0.3


def _score_industry(industry: str | None) -> float:
    """1.0 for high-value B2B industries, 0.5 otherwise, 0.3 if unknown."""
    if not industry:
        return 0.3
    return 1.0 if industry in HIGH_VALUE_INDUSTRIES else 0.5


def _score_revenue_band(band: str | None) -> float:
    """Lookup from band to 0-1 score."""
    if not band:
        return 0.3
    return _REVENUE_SCORES.get(band, 0.3)


def _score_hiring(hiring: bool | None) -> float:
    """Active hiring is a strong positive signal."""
    if hiring is None:
        return 0.3
    return 1.0 if hiring else 0.2


def _score_funding(months_ago: int | None) -> float:
    """More recent funding = higher score."""
    if months_ago is None:
        return 0.3  # neutral
    if months_ago <= 6:
        return 1.0
    elif months_ago <= 12:
        return 0.8
    elif months_ago <= 24:
        return 0.5
    else:
        return 0.2


def _score_tech_signals(signals: list[str] | None) -> float:
    """More tech signals = better data quality / more sophisticated prospect."""
    if not signals:
        return 0.1
    count = len(signals)
    if count >= 4:
        return 1.0
    elif count >= 2:
        return 0.7
    else:
        return 0.4


def _score_data_completeness(prospect: EnrichedProspect) -> float:
    """Proportion of key fields that are non-null (0-1)."""
    fields = [
        prospect.domain,
        prospect.industry or prospect.enriched_industry,
        prospect.employee_count or prospect.enriched_employee_count,
        prospect.country,
        prospect.contact_email,
        prospect.revenue_band,
        prospect.founded_year,
        prospect.tech_signals,
        prospect.hiring_now,
    ]
    filled = sum(1 for f in fields if f is not None)
    return filled / len(fields)


def score_prospect(prospect: EnrichedProspect) -> float:
    """
    Compute a 0-100 score for a single prospect.

    Uses the enriched data preferentially (it's from the authoritative
    API), falling back to the original record data where enrichment
    was partial or missing.
    """
    w = SCORING_WEIGHTS

    # Prefer enriched values, fall back to original
    emp = prospect.enriched_employee_count or prospect.employee_count
    industry = prospect.enriched_industry or prospect.industry

    total = 0.0
    total += _score_employee_count(emp) * w["employee_count"]
    total += _score_industry(industry) * w["industry"]
    total += _score_revenue_band(prospect.revenue_band) * w["revenue_band"]
    total += _score_hiring(prospect.hiring_now) * w["hiring_now"]
    total += _score_funding(prospect.last_funding_months_ago) * w["last_funding_months_ago"]
    total += _score_tech_signals(prospect.tech_signals) * w["tech_signals"]
    total += _score_data_completeness(prospect) * w["data_completeness"]

    return round(total, 2)


def score_all(prospects: list[EnrichedProspect]) -> list[EnrichedProspect]:
    """Score and sort all prospects (highest first)."""
    for p in prospects:
        p.score = score_prospect(p)

    prospects.sort(key=lambda p: p.score, reverse=True)

    logger.info(
        "Scoring complete: scores range %.1f - %.1f",
        prospects[-1].score if prospects else 0,
        prospects[0].score if prospects else 0,
    )
    return prospects
