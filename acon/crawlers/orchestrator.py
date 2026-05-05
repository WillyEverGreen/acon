"""Crawler orchestration for fast, deep, and max discovery modes."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
import logging
from typing import Callable, Optional

from ..config import CRAWLER_CONFIG, SCAN_MODES, resolve_max_pages
from .discovery_crawler import DiscoveryCrawler
from .common import detect_critical_page_type, normalize_url, priority_path_boost
from .dom_crawler import DOMCrawler
from .models import CrawledURL, SitemapURL
from .sitemap_crawler import SitemapCrawler

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _MergedURL:
    url: str
    depth: int
    base_priority: float
    page_type: Optional[str]
    sources: set[str]
    priority_score: float = 0.0


class CrawlerOrchestrator:
    """Run discovery crawlers in parallel and return prioritized URL lists."""

    def __init__(
        self,
        *,
        sitemap_crawler: Optional[SitemapCrawler] = None,
        discovery_factory: Optional[Callable[..., DiscoveryCrawler]] = None,
        dom_crawler: Optional[DOMCrawler] = None,
    ) -> None:
        self.sitemap_crawler = sitemap_crawler or SitemapCrawler()
        self.discovery_factory = discovery_factory or (lambda **kwargs: DiscoveryCrawler(**kwargs))
        self.dom_crawler = dom_crawler or DOMCrawler()

    async def discover_urls(self, seed_url: str, scan_mode: str, max_pages: int) -> list[str]:
        """Discover and prioritize URLs for the requested scan mode."""
        mode_key = scan_mode.lower()
        mode_cfg = SCAN_MODES.get(mode_key)
        if mode_cfg is None:
            raise ValueError(f"Unsupported scan_mode: {scan_mode}")

        cap = max(1, int(max_pages))
        max_depth = mode_cfg.get("max_depth", 2)

        sitemap_results: list[SitemapURL] = []
        discovery_results: list[CrawledURL] = []
        dom_results: list[CrawledURL] = []

        if mode_key == "fast":
            sitemap_results = await self._run_sitemap_with_timeout(
                seed_url,
                max_pages=mode_cfg["max_pages_ceiling"],
                timeout_seconds=8.0,
            )
            has_sitemap = len(sitemap_results) > 0
            resolved_cap = min(resolve_max_pages(mode_key, has_sitemap), cap)

            if not sitemap_results:
                discovery_crawler = self.discovery_factory(
                    max_depth=max_depth,
                    max_pages=resolved_cap,
                )
                discovery_results = await self._safe_crawl_discovery(discovery_crawler, seed_url)

        elif mode_key == "deep":
            discovery_crawler = self.discovery_factory(
                max_depth=max_depth,
                max_pages=mode_cfg["max_pages_ceiling"],
            )
            sitemap_task = asyncio.create_task(
                self._safe_discover_sitemap(seed_url, mode_cfg["max_pages_ceiling"])
            )
            discovery_task = asyncio.create_task(self._safe_crawl_discovery(discovery_crawler, seed_url))
            sitemap_results, discovery_results = await asyncio.gather(sitemap_task, discovery_task)
            has_sitemap = len(sitemap_results) > 0
            resolved_cap = min(resolve_max_pages(mode_key, has_sitemap), cap)

        elif mode_key == "max":
            discovery_crawler = self.discovery_factory(
                max_depth=max_depth,
                max_pages=mode_cfg["max_pages_ceiling"],
            )
            sitemap_task = asyncio.create_task(
                self._safe_discover_sitemap(seed_url, mode_cfg["max_pages_ceiling"])
            )
            discovery_task = asyncio.create_task(self._safe_crawl_discovery(discovery_crawler, seed_url))
            dom_task = asyncio.create_task(
                self._safe_crawl_dom(self.dom_crawler, seed_url, mode_cfg["max_pages_ceiling"])
            )
            sitemap_results, discovery_results, dom_results = await asyncio.gather(
                sitemap_task,
                discovery_task,
                dom_task,
            )
            has_sitemap = len(sitemap_results) > 0
            resolved_cap = min(resolve_max_pages(mode_key, has_sitemap), cap)

        merged = self._merge_results(sitemap_results, discovery_results, dom_results)
        prioritized = self._prioritize(merged)
        selected = self._ensure_critical_path_coverage(prioritized, resolved_cap)
        return [item.url for item in selected[:resolved_cap]]

    async def _run_sitemap_with_timeout(self, seed_url: str, max_pages: int, timeout_seconds: float) -> list[SitemapURL]:
        try:
            return await asyncio.wait_for(
                self._safe_discover_sitemap(seed_url, max_pages),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Sitemap crawl timed out for %s", seed_url)
            return []

    async def _safe_discover_sitemap(self, seed_url: str, max_pages: int) -> list[SitemapURL]:
        try:
            return await self.sitemap_crawler.discover(seed_url, max_pages=max_pages)
        except Exception as exc:
            logger.warning("Sitemap discovery failed for %s: %s", seed_url, exc)
            return []

    @staticmethod
    async def _safe_crawl_discovery(crawler: DiscoveryCrawler, seed_url: str) -> list[CrawledURL]:
        try:
            return await crawler.crawl(seed_url)
        except Exception as exc:
            logger.warning("Discovery crawl failed for %s: %s", seed_url, exc)
            return []

    @staticmethod
    async def _safe_crawl_dom(crawler: DOMCrawler, seed_url: str, max_pages: int) -> list[CrawledURL]:
        try:
            return await crawler.crawl(seed_url, max_pages=max_pages)
        except Exception as exc:
            logger.warning("DOM crawl failed for %s: %s", seed_url, exc)
            return []

    def _merge_results(
        self,
        sitemap_results: list[SitemapURL],
        discovery_results: list[CrawledURL],
        dom_results: list[CrawledURL],
    ) -> list[_MergedURL]:
        merged: dict[str, _MergedURL] = {}
        default_priority = float(CRAWLER_CONFIG["sitemap"]["default_priority"])

        def upsert(url: str, source: str, depth: int, priority: float) -> None:
            normalized = normalize_url(url)
            item = merged.get(normalized)
            if item is None:
                merged[normalized] = _MergedURL(
                    url=normalized,
                    depth=depth,
                    base_priority=priority,
                    page_type=detect_critical_page_type(normalized),
                    sources={source},
                )
                return

            item.sources.add(source)
            item.depth = min(item.depth, depth)
            item.base_priority = max(item.base_priority, priority)
            if item.page_type is None:
                item.page_type = detect_critical_page_type(normalized)

        for row in sitemap_results:
            if isinstance(row, SitemapURL):
                upsert(row.url, "sitemap", int(row.depth), float(row.priority))
            else:
                upsert(str(getattr(row, "url")), "sitemap", int(getattr(row, "depth", 0)), float(getattr(row, "priority", default_priority)))

        for row in discovery_results:
            if isinstance(row, CrawledURL):
                upsert(row.url, "discovery", int(row.depth), default_priority)
            else:
                upsert(str(getattr(row, "url")), "discovery", int(getattr(row, "depth", 0)), default_priority)

        for row in dom_results:
            if isinstance(row, CrawledURL):
                upsert(row.url, "dom", int(row.depth), default_priority)
            else:
                upsert(str(getattr(row, "url")), "dom", int(getattr(row, "depth", 0)), default_priority)

        return list(merged.values())

    def _prioritize(self, items: list[_MergedURL]) -> list[_MergedURL]:
        cross_boost = float(CRAWLER_CONFIG["orchestrator"]["cross_crawler_agreement_boost"])
        shallow_boost = float(CRAWLER_CONFIG["orchestrator"]["shallow_depth_boost"])
        shallow_depth_threshold = int(CRAWLER_CONFIG["orchestrator"]["shallow_depth_threshold"])

        for item in items:
            score = item.base_priority
            score += priority_path_boost(item.url)
            if "sitemap" in item.sources and "discovery" in item.sources:
                score += cross_boost
            if item.depth <= shallow_depth_threshold:
                score += shallow_boost
            item.priority_score = score

        return sorted(items, key=lambda row: (-row.priority_score, row.depth, row.url))

    @staticmethod
    def _ensure_critical_path_coverage(items: list[_MergedURL], cap: int) -> list[_MergedURL]:
        if not items:
            return []

        selected = list(items[:cap])
        critical_types = {row.page_type for row in items if row.page_type in {"auth", "form", "product"}}
        if not critical_types:
            return selected

        selected_urls = {row.url for row in selected}
        selected_types = {row.page_type for row in selected}

        for missing_type in sorted(critical_types - selected_types):
            promoted = next(
                (row for row in items if row.page_type == missing_type and row.url not in selected_urls),
                None,
            )
            if promoted is None:
                continue

            selected.append(promoted)
            selected_urls.add(promoted.url)

            if len(selected) <= cap:
                continue

            type_counts = Counter(row.page_type for row in selected if row.page_type in critical_types)
            removable_index = None
            for idx in range(len(selected) - 1, -1, -1):
                candidate = selected[idx]
                page_type = candidate.page_type
                if page_type in critical_types and type_counts[page_type] <= 1:
                    continue
                removable_index = idx
                break

            if removable_index is None:
                removable_index = len(selected) - 1

            removed = selected.pop(removable_index)
            selected_urls.discard(removed.url)

        selected.sort(key=lambda row: (-row.priority_score, row.depth, row.url))
        return selected
