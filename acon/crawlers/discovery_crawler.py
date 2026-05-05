"""Discovery crawler for same-origin link discovery."""

from __future__ import annotations

import asyncio
from collections import deque
import logging
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import AsyncSession

from ..config import CRAWLER_CONFIG
from .common import (
    extract_anchor_hrefs,
    get_origin,
    has_binary_extension,
    http_get_with_backoff,
    is_disallowed,
    is_same_origin,
    normalize_url,
    resolve_url,
    should_skip_href,
)
from .models import CrawledURL

logger = logging.getLogger(__name__)


_CRAWL4AI_AVAILABLE = False
try:
    from crawl4ai import AsyncWebCrawler

    _CRAWL4AI_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    AsyncWebCrawler = None  # type: ignore[assignment]


class DiscoveryCrawler:
    """Crawl links level-by-level from a seed URL using discovery traversal."""

    def __init__(
        self,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        concurrency: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        cfg = CRAWLER_CONFIG["discovery"]
        self.max_depth = int(max_depth if max_depth is not None else cfg["default_max_depth"])
        self.max_pages = int(max_pages if max_pages is not None else cfg["default_max_pages"])
        self.concurrency = int(concurrency if concurrency is not None else cfg["default_concurrency"])
        self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None else cfg["timeout_seconds"])
        self.default_priority = float(cfg["default_priority"])

        self.visited: set[str] = set()
        self.queue: asyncio.Queue[tuple[str, int, Optional[str]]] = asyncio.Queue()

    async def crawl(self, seed_url: str, *, disallow_set: frozenset[str] = frozenset()) -> list[CrawledURL]:
        """Discover same-origin URLs from a seed page with bounded traversal."""
        self.visited = set()
        semaphore = asyncio.Semaphore(max(1, int(self.concurrency)))

        seed_fetch_url = seed_url.strip()
        normalized_seed = normalize_url(seed_fetch_url)
        base_origin = get_origin(normalized_seed)

        pending = deque([(seed_fetch_url, 0, None)])
        enqueued = {normalized_seed}
        results: list[CrawledURL] = []

        while pending and len(results) < self.max_pages:
            current_depth = pending[0][1]
            level_items: list[tuple[str, int, Optional[str]]] = []

            while pending and pending[0][1] == current_depth and len(results) < self.max_pages:
                level_items.append(pending.popleft())

            fetch_targets: list[tuple[str, str, int]] = []

            for url, depth, parent in level_items:
                normalized = normalize_url(url)
                if normalized in self.visited:
                    continue

                self.visited.add(normalized)
                results.append(
                    CrawledURL(
                        url=normalized,
                        source="discovery",
                        depth=depth,
                        discovered_from=parent,
                        priority=self.default_priority,
                    )
                )

                if len(results) >= self.max_pages:
                    break

                if depth < self.max_depth:
                    fetch_targets.append((url, normalized, depth))

            if not fetch_targets or len(results) >= self.max_pages:
                continue

            fetch_tasks = [
                asyncio.create_task(self._fetch_links(parent_url, base_origin, semaphore=semaphore, disallow_set=disallow_set))
                for parent_url, _, _ in fetch_targets
            ]

            level_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for (parent_fetch_url, parent_normalized, parent_depth), links_result in zip(fetch_targets, level_results):
                if isinstance(links_result, Exception):
                    logger.warning("Discovery link extraction failed for %s: %s", parent_fetch_url, links_result)
                    continue

                child_depth = parent_depth + 1
                if child_depth > self.max_depth:
                    continue

                for child_url in links_result:
                    normalized_child = normalize_url(child_url)
                    if normalized_child in self.visited or normalized_child in enqueued:
                        continue
                    enqueued.add(normalized_child)
                    pending.append((normalized_child, child_depth, parent_normalized))

        return results[: self.max_pages]

    async def _fetch_links(
        self,
        url: str,
        base_origin: str,
        *,
        semaphore: asyncio.Semaphore,
        disallow_set: frozenset[str],
    ) -> list[str]:
        async with semaphore:
            html = await self._fetch_html(url)

        if not html:
            return []

        links: list[str] = []
        for href in extract_anchor_hrefs(html):
            if should_skip_href(href):
                continue

            absolute = resolve_url(url, href)
            parsed = urlparse(absolute)
            if parsed.scheme.lower() not in {"http", "https"}:
                continue

            normalized = normalize_url(absolute)
            if should_skip_href(normalized):
                continue
            if not is_same_origin(normalized, base_origin):
                continue
            if is_disallowed(normalized, disallow_set):
                continue
            if has_binary_extension(normalized):
                continue

            links.append(normalized)

        deduped = sorted(set(links))
        return deduped

    async def _fetch_html(self, url: str) -> Optional[str]:
        if _CRAWL4AI_AVAILABLE and AsyncWebCrawler is not None:
            try:
                async with AsyncWebCrawler() as crawler:
                    # Wrap in wait_for to prevent indefinite hangs if playwright gets stuck
                    result = await asyncio.wait_for(
                        crawler.arun(url=url),
                        timeout=self.timeout_seconds
                    )
                html = self._extract_html_from_crawl4ai_result(result)
                if html:
                    return html
            except Exception:
                logger.debug("crawl4ai fetch failed for %s; falling back to curl_cffi", url)

        try:
            async with AsyncSession(impersonate="chrome") as client:
                response = await http_get_with_backoff(
                    url,
                    client=client,
                    max_retries=2,
                    timeout_seconds=self.timeout_seconds,
                )
            if int(response.status_code) >= 400:
                return None
            return str(response.text or "")
        except Exception:
            return None

    @staticmethod
    def _extract_html_from_crawl4ai_result(result: object) -> Optional[str]:
        if result is None:
            return None

        if isinstance(result, dict):
            html = result.get("html") or result.get("cleaned_html")
            return str(html) if html else None

        html = getattr(result, "html", None)
        if html:
            return str(html)

        cleaned_html = getattr(result, "cleaned_html", None)
        if cleaned_html:
            return str(cleaned_html)

        return None
