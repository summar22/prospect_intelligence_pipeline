"""Tests for Stage 2 — Entity Resolution."""

import pytest
from pipeline.models import NormalizedProspect
from pipeline.entity_resolution import (
    _company_key,
    _domain_root,
    resolve_entities,
)


class TestCompanyKey:
    def test_basic(self):
        assert _company_key("Northwind Logistics Partners Inc") == "northwind_logistics"

    def test_strips_suffixes(self):
        assert _company_key("Cedar Systems Group Ltd") == "cedar_systems"

    def test_all_suffixes(self):
        # If name is only suffixes, returns empty
        assert _company_key("Inc LLC") == ""

    def test_single_word(self):
        assert _company_key("Foxglove Energy International") == "foxglove_energy"


class TestDomainRoot:
    def test_basic(self):
        assert _domain_root("northwindlogistics.com") == "northwindlogistics"

    def test_subdomain_stripped_earlier(self):
        # Domain cleaning already stripped www, so this tests just TLD removal
        assert _domain_root("brightpathanalytic.com") == "brightpathanalytic"


class TestResolveEntities:
    def _make_record(self, rid, name, domain=None, **kwargs):
        return NormalizedProspect(
            record_id=rid,
            company_name=name,
            domain=domain,
            **kwargs,
        )

    def test_merges_same_company_key(self):
        """Records with same company key should merge."""
        records = [
            self._make_record("R1", "Northwind Logistics Partners Inc", "northwindlogistics.com"),
            self._make_record("R2", "Northwind Logistics Co", "northwindlogistics.com"),
            self._make_record("R3", "Northwind Logistics Global Ltd", "northwindlogistics.com"),
        ]
        entities, stats = resolve_entities(records)
        assert len(entities) == 1
        assert len(entities[0].source_record_ids) == 3

    def test_distinct_companies_stay_separate(self):
        """Unrelated companies should not merge."""
        records = [
            self._make_record("R1", "Northwind Logistics", "northwindlogistics.com"),
            self._make_record("R2", "Cedar Systems", "cedarsystems.com"),
            self._make_record("R3", "Foxglove Energy", "foxgloveenergy.com"),
        ]
        entities, stats = resolve_entities(records)
        assert len(entities) == 3

    def test_merge_by_domain_root(self):
        """Records sharing a domain root should merge even if names differ."""
        records = [
            self._make_record("R1", "Quill Software Co", "quillsoftware.com"),
            self._make_record("R2", "Quill Software Partners", "quillsoftwarepartn.com"),
        ]
        entities, stats = resolve_entities(records)
        # Both have company key "quill_software", so they merge
        assert len(entities) == 1

    def test_shortest_name_wins(self):
        """Merged entity should have the shortest company name."""
        records = [
            self._make_record("R1", "Cedar Systems Group Inc.", "cedarsystems.com"),
            self._make_record("R2", "Cedar Systems", "cedarsystems.com"),
            self._make_record("R3", "Cedar Systems International Ltd.", "cedarsystemsintern.com"),
        ]
        entities, _ = resolve_entities(records)
        assert len(entities) == 1
        assert entities[0].company_name == "Cedar Systems"

    def test_stats_correct(self):
        records = [
            self._make_record("R1", "Alpha Corp", "alpha.com"),
            self._make_record("R2", "Alpha Inc", "alpha.com"),
            self._make_record("R3", "Beta LLC", "beta.com"),
        ]
        entities, stats = resolve_entities(records)
        assert stats["input_records"] == 3
        assert stats["entities_produced"] == 2
        assert stats["clusters_with_merges"] == 1
