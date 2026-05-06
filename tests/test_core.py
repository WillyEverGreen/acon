"""Smoke tests for acon-intel.

These tests verify the public API surface, core utilities, and a mocked
end-to-end crawl without requiring network access.
"""

import asyncio
import pytest

# ---------------------------------------------------------------------------
# 1. Public import surface
# ---------------------------------------------------------------------------

def test_top_level_imports():
    from acon import SiteCrawlOrchestrator, CrawlConfig, SiteTopology  # noqa: F401
    assert SiteCrawlOrchestrator is not None
    assert CrawlConfig is not None
    assert SiteTopology is not None


def test_crawlers_package_imports():
    from acon.crawlers import (  # noqa: F401
        SiteCrawlOrchestrator,
        CrawlConfig,
        SitemapCrawler,
        SitemapURL,
        CrawledURL,
        DOMCrawler,
        DiscoveryCrawler,
    )


# ---------------------------------------------------------------------------
# 2. URL normalization
# ---------------------------------------------------------------------------

def test_normalize_url_strips_tracking_params():
    from acon.crawlers.common import normalize_url
    raw = "https://Example.COM/path/?utm_source=google&q=test"
    result = normalize_url(raw)
    assert "utm_source" not in result
    assert "q=test" in result
    assert result.startswith("https://example.com")


def test_normalize_url_strips_trailing_slash():
    from acon.crawlers.common import normalize_url
    assert normalize_url("https://example.com/path/") == "https://example.com/path"


def test_normalize_url_for_dedup_deduplicates():
    from acon.crawlers.crawler import normalize_url_for_dedup
    a = normalize_url_for_dedup("https://Example.com/Path/")
    b = normalize_url_for_dedup("https://example.com/Path")
    assert a == b


def test_should_skip_href_rejects_non_http():
    from acon.crawlers.common import should_skip_href
    assert should_skip_href("mailto:user@example.com") is True
    assert should_skip_href("javascript:void(0)") is True
    assert should_skip_href("#anchor") is True
    assert should_skip_href("https://example.com") is False


# ---------------------------------------------------------------------------
# 3. Topology detection
# ---------------------------------------------------------------------------

def test_detect_topology_empty_input():
    from acon.utils.topology_detector import detect_topology
    from acon.config import SiteTopology
    result = detect_topology([])
    assert result.topology == SiteTopology.SINGLE_PAGE
    assert result.crawl_urls == []


def test_detect_topology_paginated():
    from acon.utils.topology_detector import detect_topology
    from acon.config import SiteTopology
    urls = (
        ["https://example.com/"]
        + [f"https://example.com/page/{i}" for i in range(1, 20)]
        + [f"https://example.com/blog/post-{i}" for i in range(10)]
    )
    result = detect_topology(urls)
    assert result.topology == SiteTopology.PAGINATED


def test_detect_topology_single_page():
    from acon.utils.topology_detector import detect_topology
    from acon.config import SiteTopology
    result = detect_topology(["https://app.example.com/"], rendered_page_count=1)
    assert result.topology == SiteTopology.SINGLE_PAGE


# ---------------------------------------------------------------------------
# 4. Failure taxonomy
# ---------------------------------------------------------------------------

def test_normalize_failure_rate_limited():
    from acon.utils.failure_taxonomy import normalize_failure, DegradedReason
    assert normalize_failure("rate_limited") == DegradedReason.RATE_LIMITED
    assert normalize_failure(429) == DegradedReason.RATE_LIMITED


def test_normalize_failure_bot_wall():
    from acon.utils.failure_taxonomy import normalize_failure, DegradedReason
    assert normalize_failure("cloudflare_block") == DegradedReason.BOT_WALL
    assert normalize_failure(403) == DegradedReason.BOT_WALL


def test_normalize_failure_connectivity():
    from acon.utils.failure_taxonomy import normalize_failure, DegradedReason
    assert normalize_failure("getaddrinfo failed: Name not resolved") == DegradedReason.CONNECTIVITY_BLOCKED


def test_classify_failure_reason_is_string():
    from acon.utils.failure_taxonomy import classify_failure_reason
    result = classify_failure_reason(Exception("connection reset"))
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 5. CrawlSession queue semantics
# ---------------------------------------------------------------------------

def test_crawl_session_dedup():
    from acon.crawlers.crawler import CrawlSession
    session = CrawlSession()
    ok1, _ = session.enqueue("https://example.com/page", depth=0, page_type="standard", page_weight=0.5)
    ok2, _ = session.enqueue("https://example.com/page/", depth=0, page_type="standard", page_weight=0.5)  # same after normalization
    assert ok1 is True
    assert ok2 is False
    assert session.pages_skipped_dedup == 1


def test_crawl_session_priority_order():
    from acon.crawlers.crawler import CrawlSession
    session = CrawlSession()
    session.enqueue("https://example.com/blog/post", depth=1, page_type="standard", page_weight=0.5)
    session.enqueue("https://example.com/", depth=0, page_type="homepage", page_weight=1.0)
    session.enqueue("https://example.com/nav", depth=1, page_type="nav", page_weight=0.8)

    first = session.dequeue_prioritized()
    assert first is not None
    assert first.page_type == "homepage"


# ---------------------------------------------------------------------------
# 6. CrawlConfig normalization
# ---------------------------------------------------------------------------

def test_crawlconfig_normalizes_scan_mode():
    from acon.crawlers.crawl_orchestrator import CrawlConfig
    cfg = CrawlConfig(scan_mode="minimal").normalized()
    assert cfg.scan_mode == "fast"

    cfg2 = CrawlConfig(scan_mode="thorough").normalized()
    assert cfg2.scan_mode == "max"


def test_crawlconfig_clamps_concurrency():
    from acon.crawlers.crawl_orchestrator import CrawlConfig
    cfg = CrawlConfig(scan_mode="deep", concurrency=99).normalized()
    assert cfg.concurrency <= 3  # deep mode cap is 3


# ---------------------------------------------------------------------------
# 7. Mocked end-to-end crawl (no network)
# ---------------------------------------------------------------------------

async def _mock_fetch(**kwargs):
    return {"fetch_status": "success", "data": []}


@pytest.mark.asyncio
async def test_crawl_site_discovery_only():
    from acon import SiteCrawlOrchestrator, CrawlConfig
    brain = SiteCrawlOrchestrator(fetch_callable=_mock_fetch)
    config = CrawlConfig(max_pages=3, discovery_only=True, scan_mode="fast")
    result = await brain.crawl_site("https://example.com", config)
    assert result["site_url"] == "https://example.com"
    assert "page_summaries" in result
    assert "crawl_meta" in result
    assert result["crawl_meta"]["reflection"]["intelligence_score"] >= 0.0


@pytest.mark.asyncio
async def test_crawl_site_returns_topology():
    from acon import SiteCrawlOrchestrator, CrawlConfig
    brain = SiteCrawlOrchestrator(fetch_callable=_mock_fetch)
    config = CrawlConfig(max_pages=1, scan_mode="fast")
    result = await brain.crawl_site("https://example.com", config)
    assert "topology" in result
