"""
Stage 2 — Entity Resolution
============================
Detects and merges records that refer to the same company.

Strategy
--------
The dataset contains many variants of the same company — e.g.
"Northwind Logistics Partners Inc", "northwind logistics global inc",
"Northwind Logistics Co".  They often share the same base domain
(``northwindlogistics.com``) but appear under slightly different
full-length names.

We use a *two-key clustering* approach:

1.  **Company key**: extract the first two "meaningful" words of the
    name after stripping common suffixes (Inc, LLC, Group, ...).
    "Northwind Logistics Partners Inc" -> ``northwind_logistics``.

2.  **Domain root**: the domain with its TLD removed, lowered.
    ``northwindlogistics.com`` -> ``northwindlogistics``.

Records are placed in the same cluster if they share the same
company key OR if their domain roots overlap.  We do this with a
union-find so transitive matches are caught.

Merge rules
-----------
Within each cluster the "canonical" record is built by:
*  company_name  — shortest variant (most canonical / least noisy)
*  domain        — most common non-null, prefer shorter
*  industry      — mode of non-null values
*  employee_count— median of all parsed values
*  country       — mode
*  contact_email — first valid value
*  source_captured_at — latest date
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from statistics import median
from typing import Optional

from pipeline.models import NormalizedProspect, ResolvedEntity

logger = logging.getLogger(__name__)

# Suffixes stripped when building the company key
_SUFFIXES = {
    "inc", "inc.", "incorporated", "llc", "ltd", "ltd.", "co", "co.",
    "corp", "corp.", "corporation", "group", "holdings", "partners",
    "international", "global", "the", "of",
}


# ── Union-Find ───────────────────────────────────────────────────────────────

class UnionFind:
    """Disjoint-set with path compression and union by rank."""

    def __init__(self):
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


# ── Key extraction ───────────────────────────────────────────────────────────

def _company_key(name: str) -> str:
    """
    Extract first two meaningful words, lowered, joined by underscore.

    "Northwind Logistics Partners Inc" -> "northwind_logistics"
    "Cedar Systems Group Ltd"          -> "cedar_systems"
    """
    words = name.lower().split()
    meaningful = [w for w in words if w not in _SUFFIXES]
    key = "_".join(meaningful[:2])
    return key


def _domain_root(domain: str) -> str:
    """
    Strip TLD to get a grouping key.

    "northwindlogistics.com"  -> "northwindlogistics"
    "brightpathanalytic.com"  -> "brightpathanalytic"
    """
    parts = domain.rsplit(".", 1)
    return parts[0].lower()


# ── Clustering ───────────────────────────────────────────────────────────────

def _cluster_records(
    records: list[NormalizedProspect],
) -> dict[str, list[NormalizedProspect]]:
    """Group records into clusters using company key + domain root."""
    uf = UnionFind()

    # Map each record to its canonical record_id for union-find
    ckey_to_rids: dict[str, list[str]] = defaultdict(list)
    droot_to_rids: dict[str, list[str]] = defaultdict(list)
    rid_to_record: dict[str, NormalizedProspect] = {}

    for r in records:
        rid_to_record[r.record_id] = r

        if r.company_name:
            ck = _company_key(r.company_name)
            if ck:
                ckey_to_rids[ck].append(r.record_id)

        if r.domain:
            dr = _domain_root(r.domain)
            if dr:
                droot_to_rids[dr].append(r.record_id)

    # Union by company key
    for rids in ckey_to_rids.values():
        for i in range(1, len(rids)):
            uf.union(rids[0], rids[i])

    # Union by domain root
    for rids in droot_to_rids.values():
        for i in range(1, len(rids)):
            uf.union(rids[0], rids[i])

    # Build clusters
    clusters: dict[str, list[NormalizedProspect]] = defaultdict(list)
    for rid, rec in rid_to_record.items():
        root = uf.find(rid)
        clusters[root].append(rec)

    return dict(clusters)


# ── Merge logic ──────────────────────────────────────────────────────────────

def _mode(values: list) -> Optional[str]:
    """Most common non-None value, or None."""
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def _merge_cluster(records: list[NormalizedProspect]) -> ResolvedEntity:
    """Merge a cluster of duplicate records into one ResolvedEntity."""
    # Company name: shortest non-empty variant
    names = [r.company_name for r in records if r.company_name]
    best_name = min(names, key=len) if names else ""

    # Domain: most common non-null, tie-break by shortest
    domains = [r.domain for r in records if r.domain]
    if domains:
        domain_counts = Counter(domains)
        max_count = domain_counts.most_common(1)[0][1]
        top_domains = [d for d, c in domain_counts.items() if c == max_count]
        best_domain = min(top_domains, key=len)
    else:
        best_domain = None

    # Industry: mode
    best_industry = _mode([r.industry for r in records])

    # Employee count: median of all non-null values
    emp_values = [r.employee_count for r in records if r.employee_count is not None]
    best_emp = int(median(emp_values)) if emp_values else None

    # Country: mode
    best_country = _mode([r.country for r in records])

    # Contact email: first valid one
    emails = [r.contact_email for r in records if r.contact_email]
    best_email = emails[0] if emails else None

    # Date: most recent
    dates = [r.source_captured_at for r in records if r.source_captured_at]
    best_date = max(dates) if dates else None  # ISO dates sort lexicographically

    return ResolvedEntity(
        entity_id=str(uuid.uuid4()),
        company_name=best_name,
        domain=best_domain,
        industry=best_industry,
        employee_count=best_emp,
        country=best_country,
        contact_email=best_email,
        source_captured_at=best_date,
        source_record_ids=sorted([r.record_id for r in records]),
    )


# ── Public API ───────────────────────────────────────────────────────────────

def resolve_entities(
    records: list[NormalizedProspect],
) -> tuple[list[ResolvedEntity], dict]:
    """
    Cluster and merge duplicates.

    Returns
    -------
    entities : list[ResolvedEntity]
    stats : dict  with merge statistics
    """
    clusters = _cluster_records(records)

    entities = []
    merge_details: list[dict] = []
    for _, members in clusters.items():
        entity = _merge_cluster(members)
        entities.append(entity)
        if len(members) > 1:
            merge_details.append({
                "entity": entity.company_name,
                "merged_count": len(members),
                "record_ids": entity.source_record_ids,
            })

    stats = {
        "input_records": len(records),
        "entities_produced": len(entities),
        "clusters_with_merges": len(merge_details),
        "largest_cluster": max((len(m["record_ids"]) for m in merge_details), default=0),
        "merge_details": merge_details,
    }
    logger.info(
        "Entity resolution: %d records -> %d entities (%d merges)",
        len(records), len(entities), len(merge_details),
    )
    return entities, stats
