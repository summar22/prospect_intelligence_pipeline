"""Tests for Stage 1 — Ingestion & Normalization."""

import pytest
from pipeline.ingestion import (
    clean_company_name,
    clean_domain,
    clean_email,
    normalize_country,
    parse_date,
    parse_employee_count,
)


class TestCleanCompanyName:
    def test_strips_whitespace(self):
        assert clean_company_name("  Foxglove Energy Group Co ") == "Foxglove Energy Group Co"

    def test_removes_commas(self):
        assert clean_company_name("northwind,logistics global inc") == "Northwind Logistics Global Inc"

    def test_title_cases(self):
        assert clean_company_name("BASALT CONSTRUCTION") == "Basalt Construction"

    def test_collapses_spaces(self):
        assert clean_company_name("  Cedar   Systems  ") == "Cedar Systems"

    def test_none_for_empty(self):
        assert clean_company_name("") is None
        assert clean_company_name(None) is None
        assert clean_company_name("   ") is None


class TestCleanDomain:
    def test_strips_protocol(self):
        assert clean_domain("https://northwindlogistics.com/") == "northwindlogistics.com"

    def test_strips_www(self):
        assert clean_domain("www.northwindlogistics.com") == "northwindlogistics.com"

    def test_lowercases(self):
        assert clean_domain("ORBITMANUFACTURING.COM") == "orbitmanufacturing.com"

    def test_none_for_empty(self):
        assert clean_domain("") is None
        assert clean_domain(None) is None

    def test_none_for_no_dot(self):
        assert clean_domain("nodot") is None


class TestParseEmployeeCount:
    def test_range_dash(self):
        assert parse_employee_count("11-50") == 30

    def test_range_to(self):
        assert parse_employee_count("10 to 210") == 110

    def test_plus(self):
        assert parse_employee_count("1000+") == 1000

    def test_tilde(self):
        assert parse_employee_count("~42") == 42

    def test_plain_number(self):
        assert parse_employee_count("130") == 130

    def test_non_numeric(self):
        assert parse_employee_count("twelve") is None

    def test_empty(self):
        assert parse_employee_count("") is None
        assert parse_employee_count(None) is None

    def test_combined_tilde_plus(self):
        # "~260" -> 260, "18+" -> 18
        assert parse_employee_count("~260") == 260
        assert parse_employee_count("18+") == 18

    def test_large_range(self):
        assert parse_employee_count("500-1000") == 750


class TestNormalizeCountry:
    def test_us_variants(self):
        assert normalize_country("us") == "US"
        assert normalize_country("USA") == "US"
        assert normalize_country("U.S.A.") == "US"
        assert normalize_country("United States") == "US"

    def test_uk_variants(self):
        assert normalize_country("UK") == "GB"
        assert normalize_country("United Kingdom") == "GB"

    def test_germany(self):
        assert normalize_country("DE") == "DE"
        assert normalize_country("Germany") == "DE"

    def test_none_for_unknown(self):
        assert normalize_country("") is None
        assert normalize_country(None) is None


class TestCleanEmail:
    def test_valid_email(self):
        assert clean_email("info@northwind.com") == "info@northwind.com"

    def test_strips_and_lowers(self):
        assert clean_email(" INFO@willow.com ") == "info@willow.com"

    def test_invalid_no_tld(self):
        assert clean_email("contact@nimbus") is None

    def test_invalid_not_email(self):
        assert clean_email("not-an-email") is None

    def test_none(self):
        assert clean_email("") is None
        assert clean_email(None) is None


class TestParseDate:
    def test_iso_format(self):
        assert parse_date("2025-08-08") == "2025-08-08"

    def test_slash_ymd(self):
        assert parse_date("2025/06/12") == "2025-06-12"

    def test_slash_dmy(self):
        assert parse_date("19/06/2025") == "2025-06-19"

    def test_named_month(self):
        assert parse_date("6 Sep 2025") == "2025-09-06"

    def test_invalid_date(self):
        assert parse_date("31/31/2025") is None

    def test_empty(self):
        assert parse_date("") is None
        assert parse_date(None) is None
