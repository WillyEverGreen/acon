"""Crawler package for multi-page URL discovery.

This module intentionally uses lazy imports to avoid package-level import
cycles during application bootstrap.
"""

__all__ = [
    "DiscoveryCrawler",
    "CrawlConfig",
    "CrawlerOrchestrator",
    "CrawledURL",
    "DOMCrawler",
    "SiteCrawlOrchestrator",
    "SitemapCrawler",
    "SitemapURL",
]


def __getattr__(name: str):
    if name == "DiscoveryCrawler":
        from .discovery_crawler import DiscoveryCrawler

        return DiscoveryCrawler

    if name in {"CrawlConfig", "SiteCrawlOrchestrator"}:
        from .crawl_orchestrator import CrawlConfig, SiteCrawlOrchestrator

        return {
            "CrawlConfig": CrawlConfig,
            "SiteCrawlOrchestrator": SiteCrawlOrchestrator,
        }[name]

    if name == "DOMCrawler":
        from .dom_crawler import DOMCrawler

        return DOMCrawler

    if name in {"CrawledURL", "SitemapURL"}:
        from .models import CrawledURL, SitemapURL

        return {
            "CrawledURL": CrawledURL,
            "SitemapURL": SitemapURL,
        }[name]

    if name == "SitemapCrawler":
        from .sitemap_crawler import SitemapCrawler

        return SitemapCrawler

    if name == "CrawlerOrchestrator":
        from .orchestrator import CrawlerOrchestrator

        return CrawlerOrchestrator

    raise AttributeError(f"module 'acon.crawlers' has no attribute '{name}'")
