"""Link extraction and deterministic page selection strategy for Phase 6 crawling."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import AsyncSession

from .common import http_get_with_backoff
from .crawler import normalize_url_for_dedup

logger = logging.getLogger(__name__)


_INTERACTION_URL_KEYWORDS = (
    "/login",
    "/signin",
    "/signup",
    "/register",
    "/checkout",
    "/cart",
    "/contact",
    "/search",
    "/account",
    "/profile",
    "/settings",
)

_INTERACTION_TEXT_KEYWORDS = (
    "sign in",
    "log in",
    "register",
    "contact",
    "search",
    "get started",
    "book",
    "buy",
    "checkout",
)

_EXCLUDED_SCHEME_PREFIXES = ("mailto:", "tel:", "javascript:", "data:")
_EXCLUDED_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".css",
    ".js",
    ".zip",
    ".xml",
)

_PAGED_PATH_PATTERN = re.compile(r"/page/\d+", re.IGNORECASE)
_ARCHIVE_PATH_PATTERN = re.compile(r"/(tag|category|archive)/", re.IGNORECASE)
_LOW_VALUE_PATH_PATTERN = re.compile(r"/(tag|archive|search|filter)/", re.IGNORECASE)


_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    async_playwright = None  # type: ignore[assignment]


@dataclass(slots=True)
class SelectedLink:
    """A normalized internal link ready for Discovery enqueueing."""

    fetch_url: str
    dedup_key: str
    page_type: str
    page_weight: float
    tier: int


class LiveDOMLinkExtractor:
    """Extract links from live DOM using Playwright with static fallback."""

    def __init__(self) -> None:
        self._driver = None
        self._browser = None

    async def start(self) -> None:
        if not _PLAYWRIGHT_AVAILABLE or async_playwright is None:
            return
        if self._browser is not None:
            return

        self._driver = await async_playwright().start()
        self._browser = await self._driver.chromium.launch(headless=True)

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._driver is not None:
            try:
                await self._driver.stop()
            except Exception:
                pass
            self._driver = None

    async def extract_links(self, fetch_url: str, timeout_s: int) -> tuple[list[dict[str, Any]], str]:
        timeout_ms = max(1000, int(timeout_s) * 1000)

        if self._browser is not None:
            page = await self._browser.new_page()
            try:
                # Use networkidle for JS-heavy sites, but fallback if it takes too long
                try:
                    await page.goto(fetch_url, wait_until="networkidle", timeout=timeout_ms)
                except Exception:
                    # Fallback to domcontentloaded if networkidle hangs
                    await page.goto(fetch_url, wait_until="domcontentloaded", timeout=timeout_ms)
                
                await page.wait_for_load_state("domcontentloaded")
                rows = await page.evaluate(
                    r"""
                    () => {
                        const anchors = Array.from(document.querySelectorAll('a[href]'));
                        return anchors.map((anchor) => {
                            const text = (anchor.textContent || '').replace(/\s+/g, ' ').trim();
                            const href = anchor.getAttribute('href') || '';
                            return {
                                href,
                                text,
                                in_nav: Boolean(anchor.closest('nav')),
                                in_header_footer: Boolean(anchor.closest('header, footer, [role="banner"], [role="contentinfo"]')),
                            };
                        });
                    }
                    """
                )
                if isinstance(rows, list):
                    html = await page.content()
                    return _sort_raw_links(rows), html
            except Exception as exc:
                logger.warning(
                    "Live DOM extraction failed for %s; using static HTML fallback: %s",
                    fetch_url,
                    exc,
                )
            finally:
                await page.close()
        else:
            logger.warning("Live DOM browser unavailable for %s; using static HTML fallback", fetch_url)

        return await self._extract_links_static(fetch_url, timeout_s)

    async def _extract_links_static(self, fetch_url: str, timeout_s: int) -> tuple[list[dict[str, Any]], str]:
        timeout = max(3.0, float(timeout_s))
        try:
            async with AsyncSession(impersonate="chrome") as client:
                response = await http_get_with_backoff(
                    fetch_url,
                    client=client,
                    max_retries=2,
                    timeout_seconds=timeout,
                )
            if int(response.status_code) >= 400:
                return [], ""
            html = str(response.text or "")
        except Exception:
            return [], ""

        soup = BeautifulSoup(html, "html.parser")
        links: list[dict[str, Any]] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            text = " ".join(str(anchor.get_text(" ", strip=True) or "").split())
            in_nav = anchor.find_parent("nav") is not None
            in_header_footer = anchor.find_parent(["header", "footer"]) is not None
            links.append(
                {
                    "href": href,
                    "text": text,
                    "in_nav": in_nav,
                    "in_header_footer": in_header_footer,
                }
            )

        return _sort_raw_links(links), html


def select_links_for_enqueue(
    raw_links: list[dict[str, Any]],
    *,
    current_fetch_url: str,
    seed_url: str,
    next_depth: int,
    disable_sampling: bool = False,
) -> tuple[list[SelectedLink], list[dict[str, str]]]:
    """Classify and filter extracted links into deterministic crawl tiers."""
    parsed_seed = urlparse(seed_url)
    seed_host = (parsed_seed.hostname or "").lower()

    selected_by_key: dict[str, SelectedLink] = {}
    skipped: list[dict[str, str]] = []

    for raw in raw_links:
        href = str(raw.get("href") or "").strip()
        if not href:
            continue

        absolute_fetch_url = urljoin(current_fetch_url, href)
        skip_reason = _skip_reason(
            absolute_fetch_url, 
            seed_host=seed_host, 
            depth=next_depth,
            disable_sampling=disable_sampling
        )
        if skip_reason is not None:
            skipped.append({"url": absolute_fetch_url, "reason": skip_reason})
            continue

        dedup_key = normalize_url_for_dedup(absolute_fetch_url)
        if not dedup_key:
            skipped.append({"url": absolute_fetch_url, "reason": "exclusion_rule"})
            continue

        page_type, page_weight, tier = _classify_page_type(
            absolute_fetch_url,
            text=str(raw.get("text") or ""),
            in_nav=bool(raw.get("in_nav", False)),
            in_header_footer=bool(raw.get("in_header_footer", False)),
        )

        # Phase 6.2 reliability rule: avoid low-yield standard pages at deeper levels.
        if not disable_sampling and next_depth >= 2 and page_type == "standard":
            skipped.append({"url": absolute_fetch_url, "reason": "low_value_depth"})
            continue

        candidate = SelectedLink(
            fetch_url=absolute_fetch_url,
            dedup_key=dedup_key,
            page_type=page_type,
            page_weight=page_weight,
            tier=tier,
        )

        prior = selected_by_key.get(dedup_key)
        if prior is None or (candidate.tier, candidate.fetch_url) < (prior.tier, prior.fetch_url):
            selected_by_key[dedup_key] = candidate

    selected = sorted(
        selected_by_key.values(),
        key=lambda row: (row.tier, row.dedup_key, row.fetch_url),
    )

    skipped.sort(key=lambda row: (row.get("reason", ""), row.get("url", "")))
    return selected, skipped


def _skip_reason(url: str, *, seed_host: str, depth: int, disable_sampling: bool = False) -> str | None:
    lowered = str(url or "").strip().lower()
    if not lowered:
        return "exclusion_rule"

    if lowered.startswith(_EXCLUDED_SCHEME_PREFIXES):
        return "exclusion_rule"

    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return "exclusion_rule"

    host = (parsed.hostname or "").lower()
    if not host:
        return "exclusion_rule"

    if host != seed_host:
        return "external"

    path_lower = (parsed.path or "").lower()
    if path_lower.endswith(_EXCLUDED_EXTENSIONS):
        return "exclusion_rule"

    # Relax exclusion rules if sampling is disabled (for demos/comprehensive crawls)
    if disable_sampling:
        return None

    if _LOW_VALUE_PATH_PATTERN.search(path_lower):
        return "low_value_pattern"

    if depth > 1 and _PAGED_PATH_PATTERN.search(path_lower):
        return "exclusion_rule"

    query = parse_qs(parsed.query or "", keep_blank_values=True)
    if any(k.lower() in {"page", "filter", "sort"} for k in query.keys()):
        return "low_value_pattern"
    if depth > 1 and any(k.lower() in {"page", "offset", "cursor"} for k in query.keys()):
        return "exclusion_rule"

    if depth > 2 and _ARCHIVE_PATH_PATTERN.search(path_lower):
        return "exclusion_rule"

    return None


def _classify_page_type(
    url: str,
    *,
    text: str,
    in_nav: bool,
    in_header_footer: bool,
) -> tuple[str, float, int]:
    lowered_url = (url or "").lower()
    lowered_text = " ".join(str(text or "").lower().split())

    if any(keyword in lowered_url for keyword in _INTERACTION_URL_KEYWORDS):
        return "interaction", 0.9, 2

    if any(keyword in lowered_text for keyword in _INTERACTION_TEXT_KEYWORDS):
        return "interaction", 0.9, 2

    if in_nav or in_header_footer or "category" in lowered_url or "page" in lowered_url:
        return "nav", 0.8, 3

    return "standard", 0.7, 4


def _sort_raw_links(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        href = str((row or {}).get("href") or "").strip()
        if not href:
            continue
        normalized.append(
            {
                "href": href,
                "text": " ".join(str((row or {}).get("text") or "").split()),
                "in_nav": bool((row or {}).get("in_nav", False)),
                "in_header_footer": bool((row or {}).get("in_header_footer", False)),
            }
        )

    normalized.sort(
        key=lambda item: (
            item["href"],
            item["text"],
            int(item["in_nav"]),
            int(item["in_header_footer"]),
        )
    )
    return normalized
