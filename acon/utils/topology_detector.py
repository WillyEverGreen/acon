"""
app/services/topology_detector.py

Classifies site topology and returns a deduplicated, template-diverse
URL list for auditing.

Design decisions (do not change without updating tests):
- Template normalization uses POSITIONAL frequency, not length heuristics.
  _find_structural_segments() returns dict[int, set[str]] so that segment
  'doctors' at position 1 and position 2 are tracked independently.
- Pagination detection runs on RAW URLs before any normalization.
- Homepage detection uses explicit root path check, not shortest URL.
- DEEP_UNIFORM threshold is 50% of non-paginated URLs with total > 20.
- Classification order: DEEP_UNIFORM > PAGINATED > MULTI_TEMPLATE > THIN.
- SPA detection requires len(unique_urls) == 1 AND rendered_page_count <= 1
  (strict, not heuristic).
- Input capped at MAX_URLS_FOR_TOPOLOGY before processing.
- Thin site classification runs AFTER normalization (not as early-return).
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import NamedTuple
from urllib.parse import urlparse

from ..config import SiteTopology, TOPOLOGY_PAGES_PER_TEMPLATE

logger = logging.getLogger(__name__)

MAX_URLS_FOR_TOPOLOGY = 500

# ── Pagination patterns ───────────────────────────────────────────────────────

PAGINATION_PATTERNS = [
    re.compile(r"/page/\d+",          re.IGNORECASE),
    re.compile(r"/p/\d+",             re.IGNORECASE),
    re.compile(r"[?&]page=\d+",       re.IGNORECASE),
    re.compile(r"[?&]offset=\d+",     re.IGNORECASE),
    re.compile(r"[?&]start=\d+",      re.IGNORECASE),
    re.compile(r"[?&]p=\d+",          re.IGNORECASE),
]

UUID_PATTERN = re.compile(
    r"^[a-f0-9]{8}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{12}$",
    re.IGNORECASE,
)
HASH_PATTERN = re.compile(r"^[a-f0-9]{16,}$", re.IGNORECASE)


# ── Public result type ────────────────────────────────────────────────────────

class TopologyResult(NamedTuple):
    topology:         SiteTopology
    crawl_urls:       list   # deduplicated, template-diverse, ordered
    total_discovered: int    # raw input count after initial dedup
    templates_found:  int    # distinct normalised templates
    skipped_urls:     int    # pagination + excess template duplicates dropped


# ── Internal helpers ─────────────────────────────────────────────────────────

def _is_homepage(url: str) -> bool:
    """True iff the URL's path is a recognised root path."""
    path = urlparse(url).path
    return path in ("", "/", "/index.html", "/index.htm")


def _is_paginated(url: str) -> bool:
    """True iff the URL matches any known pagination pattern."""
    return any(p.search(url) for p in PAGINATION_PATTERNS)


def _find_structural_segments(paths: list[str]) -> dict[int, set[str]]:
    """Return position-aware structural segment set.

    A segment is *structural* if it appears in more than 30 % of all paths at
    that specific position.  The return value is a mapping from position index
    to the set of structural segments at that position.

    Keeping position context prevents cross-segment pollution: 'doctors' at
    position 1 (/consult/doctors/delhi) and at position 0 (/blog/doctors-guide)
    are evaluated independently and will each be judged by their own frequency,
    not combined.
    """
    position_counts: dict[int, Counter] = defaultdict(Counter)
    total = len(paths)

    for path in paths:
        for i, seg in enumerate(path.strip("/").split("/")):
            if seg:
                position_counts[i][seg] += 1

    structural: dict[int, set[str]] = {}
    for pos, counts in position_counts.items():
        for seg, count in counts.items():
            if count / total >= 0.30:
                structural.setdefault(pos, set()).add(seg)

    return structural


def _normalize_path(path: str, structural_segments: dict[int, set[str]]) -> str:
    """Normalise URL path to a template string.

    Structural segments (appearing in ≥30 % of paths at the *same* position)
    are kept verbatim.  Leaf/unique segments are replaced with ``{id}``,
    ``{uuid}``, or ``{slug}``.

    Example (structural = {0: {'health-wiki','consult'}}):
        /health-wiki/diabetes  →  /health-wiki/{slug}
        /consult/diabetes      →  /consult/{slug}
        (these remain distinct templates — correct)
    """
    # Strip query string so it does not affect template classification.
    clean_path = urlparse(path)._replace(query="").path
    segments = clean_path.strip("/").split("/")
    norm: list[str] = []

    for i, seg in enumerate(segments):
        if not seg:
            continue
        if seg in structural_segments.get(i, set()):
            norm.append(seg)
        elif seg.isdigit():
            norm.append("{id}")
        elif UUID_PATTERN.match(seg) or HASH_PATTERN.match(seg):
            norm.append("{uuid}")
        else:
            norm.append("{slug}")

    return "/" + "/".join(norm) if norm else "/"


def _with_homepage_first(urls: list[str], homepage: str | None) -> list[str]:
    """Return *urls* with *homepage* first, never duplicated."""
    if not homepage:
        return list(urls)
    rest = [u for u in urls if u != homepage]
    if not rest and not urls:
        return [homepage]
    return [homepage] + rest


# ── Public API ────────────────────────────────────────────────────────────────

def detect_topology(
    discovered_urls: list[str],
    rendered_page_count: int = 0,
) -> TopologyResult:
    """Classify site topology and return a crawl-ready URL list.

    Args:
        discovered_urls:    Raw discovered URL list (may have duplicates).
        rendered_page_count: Number of routes the JS renderer confirmed.
                             Only used for SPA detection.

    Returns:
        A :class:`TopologyResult` NamedTuple.
    """
    # ── Dedup and cap input ──────────────────────────────────────────────────
    unique_urls: list[str] = list(dict.fromkeys(discovered_urls))  # order-stable dedup
    total_discovered = len(unique_urls)
    unique_urls = unique_urls[:MAX_URLS_FOR_TOPOLOGY]

    if not unique_urls:
        return TopologyResult(
            topology=SiteTopology.SINGLE_PAGE,
            crawl_urls=[],
            total_discovered=0,
            templates_found=0,
            skipped_urls=0,
        )

    # ── Step 1: Homepage ─────────────────────────────────────────────────────
    homepage: str | None = next(
        (u for u in unique_urls if _is_homepage(u)),
        None,
    )

    # ── Step 2: Pagination detection on RAW URLs ─────────────────────────────
    paginated     = [u for u in unique_urls if _is_paginated(u)]
    non_paginated = [u for u in unique_urls if not _is_paginated(u)]
    pagination_ratio = len(paginated) / len(unique_urls) if unique_urls else 0.0

    # ── Step 3: Strict SPA detection ─────────────────────────────────────────
    # Only classify as SPA when *exactly one* URL was discovered AND the JS
    # renderer found at most one route.  Two URLs (e.g. / + /about) is NOT a
    # SPA — it may just be a thin site.
    if len(unique_urls) == 1 and rendered_page_count <= 1:
        logger.warning(
            "Single-page SPA detected (%s URLs, rendered=%s). "
            "JS route discovery not implemented. Coverage limited to root URL.",
            len(unique_urls),
            rendered_page_count,
        )
        return TopologyResult(
            topology=SiteTopology.SINGLE_PAGE,
            crawl_urls=[homepage] if homepage else unique_urls[:1],
            total_discovered=total_discovered,
            templates_found=1,
            skipped_urls=len(paginated),
        )

    # ── Step 4: Template normalisation on non-paginated URLs ─────────────────
    paths     = [urlparse(u)._replace(query="").path for u in non_paginated]
    structural = _find_structural_segments(paths)

    template_groups: dict[str, list[str]] = defaultdict(list)
    for url in non_paginated:
        path     = urlparse(url)._replace(query="").path
        template = _normalize_path(path, structural)
        template_groups[template].append(url)

    num_templates  = len(template_groups)
    largest_group  = max(len(v) for v in template_groups.values()) if template_groups else 0
    largest_ratio  = largest_group / len(non_paginated) if non_paginated else 0.0

    # ── Step 5: Classify topology ────────────────────────────────────────────
    # Priority: DEEP_UNIFORM > PAGINATED > MULTI_TEMPLATE > THIN
    if largest_ratio >= 0.50 and len(non_paginated) > 20:
        topology = SiteTopology.DEEP_UNIFORM
    elif pagination_ratio > 0.10:
        topology = SiteTopology.PAGINATED
    elif num_templates >= 3:
        topology = SiteTopology.MULTI_TEMPLATE
    else:
        topology = SiteTopology.THIN

    # ── Step 6: Select crawl URLs ─────────────────────────────────────────────
    pages_per_template = TOPOLOGY_PAGES_PER_TEMPLATE[topology]
    selected: list[str] = []
    skipped  = len(paginated)

    for _template, urls in sorted(
        template_groups.items(),
        # Deterministic: largest groups first; tie-break by template string.
        key=lambda kv: (-len(kv[1]), kv[0]),
    ):
        # Within a group: prefer URLs without query strings, then shallowest,
        # then shortest overall (avoids picking arbitrarily long slugs).
        candidates = sorted(
            urls,
            key=lambda u: (
                1 if urlparse(u).query else 0,
                len(urlparse(u).path.strip("/").split("/")),
                len(u),
            ),
        )
        chosen = candidates[:pages_per_template]
        selected.extend(chosen)
        skipped += len(urls) - len(chosen)

    crawl_urls = _with_homepage_first(selected, homepage)

    logger.info(
        "topology_detect topology=%s | templates=%d | discovered=%d | crawl=%d | skipped=%d",
        topology.value,
        num_templates,
        total_discovered,
        len(crawl_urls),
        skipped,
    )

    return TopologyResult(
        topology=topology,
        crawl_urls=crawl_urls,
        total_discovered=total_discovered,
        templates_found=num_templates,
        skipped_urls=skipped,
    )
