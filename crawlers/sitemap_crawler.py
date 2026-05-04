"""Sitemap crawler for canonical URL discovery."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Optional
from urllib.parse import urljoin

from defusedxml import ElementTree as SafeET
from curl_cffi import AsyncSession

from config import CRAWLER_CONFIG, SITEMAP_MAX_DEPTH, MAX_SITEMAP_DEPTH
from crawlers.common import (
    clamp,
    get_origin,
    has_binary_extension,
    http_get_with_backoff,
    is_disallowed,
    is_same_origin,
    normalize_url,
    parse_robots_disallow,
    path_depth,
    priority_path_boost,
    safe_float,
)
from crawlers.models import SitemapURL

logger = logging.getLogger(__name__)


class SitemapCrawler:
    """Discover URLs from robots-defined and fallback sitemap locations."""

    def __init__(
        self,
        *,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[AsyncSession] = None,
        max_depth: Optional[int] = None,
    ) -> None:
        cfg = CRAWLER_CONFIG["sitemap"]
        self.timeout_seconds = timeout_seconds or float(cfg["timeout_seconds"])
        self.default_max_pages = int(cfg["default_max_pages"])
        self.default_priority = float(cfg["default_priority"])
        self._fallback_paths = tuple(cfg["fallback_paths"])
        self._http_client = http_client
        self.max_depth = max(1, int(max_depth if max_depth is not None else SITEMAP_MAX_DEPTH))

    async def discover(self, base_url: str, max_pages: Optional[int] = None) -> list[SitemapURL]:
        """Discover same-origin URLs via sitemap hierarchy."""
        base_origin = get_origin(base_url)
        requested_cap = self.default_max_pages if max_pages is None else int(max_pages)
        page_cap = max(1, min(requested_cap, self.default_max_pages))

        sitemap_locations, disallow_set = await self._discover_sitemap_locations(base_origin)
        if not sitemap_locations:
            return []

        visited_sitemaps: set[str] = set()
        discovered: dict[str, SitemapURL] = {}

        for sitemap_url in sitemap_locations:
            await self._crawl_sitemap(
                sitemap_url=sitemap_url,
                base_origin=base_origin,
                visited_sitemaps=visited_sitemaps,
                discovered=discovered,
                disallow_set=disallow_set,
                depth=0,
            )

        ordered = sorted(
            discovered.values(),
            key=lambda item: (-item.priority, item.depth, item.url),
        )
        return ordered[:page_cap]

    async def _discover_sitemap_locations(self, base_origin: str) -> tuple[list[str], frozenset[str]]:
        robots_url = urljoin(base_origin + "/", "robots.txt")
        robots_text = await self._fetch_text(robots_url)
        disallow_set = parse_robots_disallow(robots_text or "")

        discovered: list[str] = []
        if robots_text:
            discovered.extend(self._extract_robots_sitemaps(robots_text, base_origin))

        if not discovered:
            for fallback_path in self._fallback_paths:
                discovered.append(urljoin(base_origin + "/", fallback_path.lstrip("/")))

        deduped: list[str] = []
        seen: set[str] = set()
        for url in discovered:
            normalized = normalize_url(url)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(url)
        return deduped, disallow_set

    @staticmethod
    def _extract_robots_sitemaps(robots_text: str, base_origin: str) -> list[str]:
        sitemaps: list[str] = []
        for raw_line in robots_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if not line.lower().startswith("sitemap:"):
                continue
            _, raw_value = line.split(":", 1)
            target = raw_value.strip()
            if not target:
                continue
            sitemaps.append(urljoin(base_origin + "/", target))
        return sitemaps

    async def _crawl_sitemap(
        self,
        *,
        sitemap_url: str,
        base_origin: str,
        visited_sitemaps: set[str],
        discovered: dict[str, SitemapURL],
        disallow_set: frozenset[str],
        depth: int = 0,
    ) -> None:
        if depth >= MAX_SITEMAP_DEPTH:
            logger.warning(
                "Sitemap depth %s reached MAX_SITEMAP_DEPTH=%s at %s. Stopping recursion.",
                depth, MAX_SITEMAP_DEPTH, sitemap_url,
            )
            return

        normalized_sitemap = normalize_url(sitemap_url)
        if normalized_sitemap in visited_sitemaps:
            return
        visited_sitemaps.add(normalized_sitemap)

        xml_text = await self._fetch_text(sitemap_url)
        if not xml_text:
            return

        try:
            root = SafeET.fromstring(xml_text)
        except SafeET.ParseError:
            logger.warning("Malformed sitemap XML at %s", sitemap_url)
            return

        root_name = self._local_name(root.tag)
        if root_name == "sitemapindex":
            for child_url in self._parse_sitemap_index(root):
                await self._crawl_sitemap(
                    sitemap_url=urljoin(sitemap_url, child_url),
                    base_origin=base_origin,
                    visited_sitemaps=visited_sitemaps,
                    discovered=discovered,
                    disallow_set=disallow_set,
                    depth=depth + 1,
                )
            return

        if root_name == "urlset":
            for item in self._parse_urlset(root):
                absolute_url = urljoin(base_origin + "/", item["loc"])
                if not is_same_origin(absolute_url, base_origin):
                    continue
                if has_binary_extension(absolute_url):
                    continue

                normalized = normalize_url(absolute_url)
                if is_disallowed(normalized, disallow_set):
                    continue
                base_priority = clamp(
                    safe_float(item.get("priority"), self.default_priority),
                    0.0,
                    1.0,
                )
                boosted_priority = clamp(base_priority + priority_path_boost(absolute_url), 0.0, 1.0)
                candidate = SitemapURL(
                    url=normalized,
                    priority=boosted_priority,
                    changefreq=(item.get("changefreq") or "unknown"),
                    lastmod=item.get("lastmod"),
                    depth=path_depth(normalized),
                )

                current = discovered.get(normalized)
                if current is None:
                    discovered[normalized] = candidate
                else:
                    replace = False
                    if candidate.priority > current.priority:
                        replace = True
                    elif candidate.priority == current.priority and candidate.depth < current.depth:
                        replace = True
                    if replace:
                        discovered[normalized] = candidate

    @staticmethod
    def _parse_sitemap_index(root: SafeET.Element) -> list[str]:
        return [
            loc
            for loc in (
                SitemapCrawler._child_text(node, "loc")
                for node in root.findall("{*}sitemap")
            )
            if loc
        ]

    @staticmethod
    def _parse_urlset(root: SafeET.Element) -> Iterable[dict[str, Optional[str]]]:
        for node in root.findall("{*}url"):
            loc = SitemapCrawler._child_text(node, "loc")
            if not loc:
                continue
            yield {
                "loc": loc,
                "priority": SitemapCrawler._child_text(node, "priority"),
                "changefreq": SitemapCrawler._child_text(node, "changefreq"),
                "lastmod": SitemapCrawler._child_text(node, "lastmod"),
            }

    @staticmethod
    def _child_text(node: SafeET.Element, child_name: str) -> Optional[str]:
        for child in node:
            if SitemapCrawler._local_name(child.tag) != child_name:
                continue
            if child.text is None:
                return None
            value = child.text.strip()
            return value or None
        return None

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    async def _fetch_text(self, url: str) -> Optional[str]:
        try:
            if self._http_client is not None:
                response = await http_get_with_backoff(
                    url,
                    client=self._http_client,
                    max_retries=2,
                    timeout_seconds=self.timeout_seconds,
                )
            else:
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
