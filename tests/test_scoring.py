"""Tests for Stage 4 — Scoring."""

import pytest
from pipeline.models import EnrichedProspect
from pipeline.scoring import score_prospect


def _make_prospect(**overrides) -> EnrichedProspect:
    defaults = dict(
        entity_id="test-1",
        company_name="Test Corp",
        domain="test.com",
        enrichment_status="success",
    )
    defaults.update(overrides)
    return EnrichedProspect(**defaults)


class TestScoring:
    def test_score_range(self):
        """Score should be between 0 and 100."""
        # Best-case prospect
        best = _make_prospect(
            enriched_employee_count=200,
            enriched_industry="Software",
            revenue_band="$250M+",
            hiring_now=True,
            last_funding_months_ago=3,
            tech_signals=["aws", "gcp", "kubernetes", "react"],
            country="US",
            contact_email="test@test.com",
            founded_year=2015,
        )
        score = score_prospect(best)
        assert 0 <= score <= 100
        assert score > 80  # should be high

    def test_worst_case_score(self):
        """Minimal data should produce a low but non-negative score."""
        worst = _make_prospect(
            enrichment_status="failed",
        )
        score = score_prospect(worst)
        assert 0 <= score <= 100
        assert score < 40  # should be low

    def test_hiring_boosts_score(self):
        base = _make_prospect(hiring_now=False)
        hiring = _make_prospect(hiring_now=True)
        assert score_prospect(hiring) > score_prospect(base)

    def test_recent_funding_boosts_score(self):
        old_funding = _make_prospect(last_funding_months_ago=30)
        new_funding = _make_prospect(last_funding_months_ago=3)
        assert score_prospect(new_funding) > score_prospect(old_funding)

    def test_mid_market_scores_higher_than_tiny(self):
        tiny = _make_prospect(enriched_employee_count=5)
        mid = _make_prospect(enriched_employee_count=200)
        assert score_prospect(mid) > score_prospect(tiny)

    def test_high_value_industry_bonus(self):
        generic = _make_prospect(enriched_industry="Gaming")
        high_val = _make_prospect(enriched_industry="Software")
        assert score_prospect(high_val) > score_prospect(generic)
