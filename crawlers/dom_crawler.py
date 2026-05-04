"""Headless DOM crawler for JavaScript-driven link discovery."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import logging
from typing import Any, Optional

from config import CRAWLER_CONFIG
from crawlers.common import (
    extract_anchor_hrefs,
    get_origin,
    has_binary_extension,
    is_same_origin,
    normalize_url,
    resolve_url,
    should_skip_href,
)
from crawlers.models import CrawledURL

logger = logging.getLogger(__name__)


_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    async_playwright = None  # type: ignore[assignment]


_CAMOUFOX_AVAILABLE = False
try:
    from camoufox.async_api import AsyncNewBrowser

    _CAMOUFOX_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    AsyncNewBrowser = None  # type: ignore[assignment]


_DOM_GLOBAL_SEMAPHORE = asyncio.Semaphore(int(CRAWLER_CONFIG["dom"]["concurrency"]))


class DOMCrawler:
    """Discover links from dynamic page states generated after interactions."""

    def __init__(
        self,
        *,
        interaction_budget_per_page: Optional[int] = None,
        scroll_steps: Optional[int] = None,
        page_timeout_seconds: Optional[float] = None,
        max_click_candidates: Optional[int] = None,
        shared_browser: Any | None = None,
    ) -> None:
        cfg = CRAWLER_CONFIG["dom"]
        self.default_max_pages = int(cfg["default_max_pages"])
        self.interaction_budget_per_page = int(
            interaction_budget_per_page
            if interaction_budget_per_page is not None
            else cfg["interaction_budget_per_page"]
        )
        self.early_stop_min_interactions = int(cfg["early_stop_min_interactions"])
        self.scroll_steps = int(scroll_steps if scroll_steps is not None else cfg["scroll_steps"])
        self.page_timeout_seconds = float(
            page_timeout_seconds if page_timeout_seconds is not None else cfg["page_timeout_seconds"]
        )
        self.max_click_candidates = int(
            max_click_candidates if max_click_candidates is not None else cfg["max_click_candidates"]
        )
        self.network_idle_timeout_ms = int(cfg["network_idle_timeout_ms"])
        self.ready_state_timeout_ms = int(cfg["ready_state_timeout_ms"])
        self.interaction_wait_ms = int(cfg["interaction_wait_ms"])
        self.scroll_wait_ms = int(cfg["scroll_wait_ms"])
        self.default_priority = float(cfg["default_priority"])
        self._shared_browser = shared_browser
        self.last_exploration_quality: dict[str, Any] = {
            "actions_taken": 0,
            "new_states": 0,
            "dom_change_ratio": 0.0,
            "early_stopped": False,
        }

    async def crawl(self, seed_url: str, max_pages: Optional[int] = None) -> list[CrawledURL]:
        """Crawl a page in multiple states and return discovered same-origin URLs."""
        discovered: dict[str, CrawledURL] = {}
        requested_max = self.default_max_pages if max_pages is None else int(max_pages)
        cap = max(1, min(requested_max, self.default_max_pages))
        base_origin = get_origin(seed_url)
        exploration_quality = {
            "actions_taken": 0,
            "new_states": 0,
            "dom_change_ratio": 0.0,
            "early_stopped": False,
        }

        async def _run() -> list[CrawledURL]:
            async with _DOM_GLOBAL_SEMAPHORE:
                page, closer = await self._open_page()
                try:
                    await self._prepare_page(page, seed_url)
                    await self._inject_mutation_observer(page)
                    await self._explore_page_states(page, seed_url, base_origin, cap, discovered, exploration_quality)
                finally:
                    await closer()
            return list(discovered.values())[:cap]

        run_task = asyncio.create_task(_run())
        try:
            results = await asyncio.wait_for(run_task, timeout=self.page_timeout_seconds)
            if exploration_quality["actions_taken"] > 0:
                exploration_quality["dom_change_ratio"] = round(
                    exploration_quality["new_states"] / exploration_quality["actions_taken"],
                    2,
                )
            exploration_quality["early_stopped"] = (
                exploration_quality["actions_taken"] >= 2 and exploration_quality["new_states"] == 0
            )
            self.last_exploration_quality = dict(exploration_quality)
            return results
        except asyncio.TimeoutError:
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
            logger.warning("DOM crawl timed out for %s. Returning partial results.", seed_url)
            self.last_exploration_quality = dict(exploration_quality)
            return list(discovered.values())[:cap]
        except Exception as exc:
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
            logger.warning("DOM crawl failed for %s: %s", seed_url, exc)
            self.last_exploration_quality = dict(exploration_quality)
            return list(discovered.values())[:cap]

    async def _explore_page_states(
        self,
        page: Any,
        seed_url: str,
        base_origin: str,
        cap: int,
        discovered: dict[str, CrawledURL],
        exploration_quality: Optional[dict[str, Any]] = None,
    ) -> None:
        if exploration_quality is None:
            exploration_quality = {
                "actions_taken": 0,
                "new_states": 0,
                "dom_change_ratio": 0.0,
                "early_stopped": False,
            }

        state_hashes: set[str] = set()
        interaction_count = 0
        new_links_discovered = 0

        added = await self._capture_state_links(
            page=page,
            seed_url=seed_url,
            base_origin=base_origin,
            state_label="initial",
            state_hashes=state_hashes,
            discovered=discovered,
            cap=cap,
        )
        new_links_discovered += added
        if added > 0:
            exploration_quality["new_states"] += 1

        # 1) Hamburger/menu interactions
        menu_candidates = await self._menu_candidates(page)
        for handle in menu_candidates:
            if interaction_count >= self.interaction_budget_per_page or len(discovered) >= cap:
                break
            clicked = await self._safe_click(handle)
            if not clicked:
                continue
            interaction_count += 1
            exploration_quality["actions_taken"] += 1
            await page.wait_for_timeout(self.interaction_wait_ms)
            added = await self._capture_state_links(
                page=page,
                seed_url=seed_url,
                base_origin=base_origin,
                state_label="after_interaction",
                state_hashes=state_hashes,
                discovered=discovered,
                cap=cap,
            )
            new_links_discovered += added
            if added > 0:
                exploration_quality["new_states"] += 1
            if interaction_count >= self.early_stop_min_interactions and new_links_discovered == 0:
                return

        # 2) Hover top navigation items
        nav_items = await self._nav_hover_candidates(page)
        for handle in nav_items:
            if interaction_count >= self.interaction_budget_per_page or len(discovered) >= cap:
                break
            hovered = await self._safe_hover(handle)
            if not hovered:
                continue
            interaction_count += 1
            exploration_quality["actions_taken"] += 1
            await page.wait_for_timeout(self.interaction_wait_ms)
            added = await self._capture_state_links(
                page=page,
                seed_url=seed_url,
                base_origin=base_origin,
                state_label="after_interaction",
                state_hashes=state_hashes,
                discovered=discovered,
                cap=cap,
            )
            new_links_discovered += added
            if added > 0:
                exploration_quality["new_states"] += 1
            if interaction_count >= self.early_stop_min_interactions and new_links_discovered == 0:
                return

        # 3) Route-change exploration for SPAs (bounded)
        route_targets = await self._route_change_candidates(page)
        for handle in route_targets:
            if interaction_count >= self.interaction_budget_per_page or len(discovered) >= cap:
                break
            clicked = await self._safe_click(handle)
            if not clicked:
                continue
            interaction_count += 1
            exploration_quality["actions_taken"] += 1
            await page.wait_for_timeout(self.interaction_wait_ms)
            added = await self._capture_state_links(
                page=page,
                seed_url=seed_url,
                base_origin=base_origin,
                state_label="after_route_change",
                state_hashes=state_hashes,
                discovered=discovered,
                cap=cap,
            )
            new_links_discovered += added
            if added > 0:
                exploration_quality["new_states"] += 1
            if interaction_count >= self.early_stop_min_interactions and new_links_discovered == 0:
                return

        # 4) Modal trigger exploration
        modal_targets = await self._modal_candidates(page)
        for handle in modal_targets:
            if interaction_count >= self.interaction_budget_per_page or len(discovered) >= cap:
                break
            clicked = await self._safe_click(handle)
            if not clicked:
                continue
            interaction_count += 1
            exploration_quality["actions_taken"] += 1
            await page.wait_for_timeout(self.interaction_wait_ms)
            added = await self._capture_state_links(
                page=page,
                seed_url=seed_url,
                base_origin=base_origin,
                state_label="after_modal",
                state_hashes=state_hashes,
                discovered=discovered,
                cap=cap,
            )
            new_links_discovered += added
            if added > 0:
                exploration_quality["new_states"] += 1
            if interaction_count >= self.early_stop_min_interactions and new_links_discovered == 0:
                return

        # 5) Scroll exploration
        for _ in range(self.scroll_steps):
            if interaction_count >= self.interaction_budget_per_page or len(discovered) >= cap:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            interaction_count += 1
            exploration_quality["actions_taken"] += 1
            await page.wait_for_timeout(self.scroll_wait_ms)
            added = await self._capture_state_links(
                page=page,
                seed_url=seed_url,
                base_origin=base_origin,
                state_label="after_scroll",
                state_hashes=state_hashes,
                discovered=discovered,
                cap=cap,
            )
            new_links_discovered += added
            if added > 0:
                exploration_quality["new_states"] += 1
            if interaction_count >= self.early_stop_min_interactions and new_links_discovered == 0:
                return

        # 6) Load-more buttons and simple pagination controls
        load_more_targets = await self._load_more_candidates(page)
        for handle in load_more_targets:
            if interaction_count >= self.interaction_budget_per_page or len(discovered) >= cap:
                break
            clicked = await self._safe_click(handle)
            if not clicked:
                continue
            interaction_count += 1
            exploration_quality["actions_taken"] += 1
            await page.wait_for_timeout(self.scroll_wait_ms)
            added = await self._capture_state_links(
                page=page,
                seed_url=seed_url,
                base_origin=base_origin,
                state_label="after_interaction",
                state_hashes=state_hashes,
                discovered=discovered,
                cap=cap,
            )
            new_links_discovered += added
            if added > 0:
                exploration_quality["new_states"] += 1
            if interaction_count >= self.early_stop_min_interactions and new_links_discovered == 0:
                return

    async def _capture_state_links(
        self,
        *,
        page: Any,
        seed_url: str,
        base_origin: str,
        state_label: str,
        state_hashes: set[str],
        discovered: dict[str, CrawledURL],
        cap: int,
    ) -> int:
        html = await page.content()
        dom_hash = hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()[:16]
        if dom_hash in state_hashes:
            return 0
        state_hashes.add(dom_hash)

        hrefs = await self._extract_links_from_page(page, html)
        added = 0

        for href in hrefs:
            if len(discovered) >= cap:
                break
            if should_skip_href(href):
                continue

            absolute = resolve_url(seed_url, href)
            normalized = normalize_url(absolute)
            if should_skip_href(normalized):
                continue
            if not is_same_origin(normalized, base_origin):
                continue
            if has_binary_extension(normalized):
                continue
            if normalized in discovered:
                continue

            discovered[normalized] = CrawledURL(
                url=normalized,
                source="dom",
                depth=0,
                discovered_from=normalize_url(seed_url),
                state=state_label,
                priority=self.default_priority,
                metadata={"dom_hash": dom_hash},
            )
            added += 1

        return added

    async def _extract_links_from_page(self, page: Any, html: str) -> list[str]:
        hrefs: list[str] = []

        try:
            values = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
            if isinstance(values, list):
                hrefs.extend([str(v) for v in values if isinstance(v, str) and v.strip()])
        except Exception:
            hrefs.extend(extract_anchor_hrefs(html))

        try:
            mutation_links = await page.evaluate("() => window.__aconMutationLinks || []")
            if isinstance(mutation_links, list):
                hrefs.extend([str(v) for v in mutation_links if isinstance(v, str) and v.strip()])
        except Exception:
            pass

        return list(dict.fromkeys(hrefs))

    async def _menu_candidates(self, page: Any) -> list[Any]:
        handles = await page.query_selector_all("button, [role='button'], [aria-label]")
        candidates: list[Any] = []
        for handle in handles[: self.max_click_candidates]:
            aria_label = (await self._safe_get_attribute(handle, "aria-label")).lower()
            text = (await self._safe_inner_text(handle)).lower()
            if any(token in aria_label for token in ("menu", "nav", "navigation")):
                candidates.append(handle)
                continue
            if any(token in text for token in ("menu", "navigation")):
                candidates.append(handle)
        return candidates

    async def _nav_hover_candidates(self, page: Any) -> list[Any]:
        handles = await page.query_selector_all("nav a, nav button, header a, header button")
        return handles[: self.max_click_candidates]

    async def _load_more_candidates(self, page: Any) -> list[Any]:
        handles = await page.query_selector_all("button, a")
        candidates: list[Any] = []
        for handle in handles[: self.max_click_candidates]:
            text = (await self._safe_inner_text(handle)).lower()
            if any(token in text for token in ("load more", "show more", "next", "more")):
                candidates.append(handle)
        return candidates

    async def _route_change_candidates(self, page: Any) -> list[Any]:
        handles = await page.query_selector_all("a[href]")
        return handles[: self.max_click_candidates]

    async def _modal_candidates(self, page: Any) -> list[Any]:
        handles = await page.query_selector_all("[aria-haspopup='dialog'], [aria-controls], button, a")
        candidates: list[Any] = []
        for handle in handles[: self.max_click_candidates]:
            text = (await self._safe_inner_text(handle)).lower()
            aria_has_popup = (await self._safe_get_attribute(handle, "aria-haspopup")).lower() == "dialog"
            aria_controls = bool((await self._safe_get_attribute(handle, "aria-controls")).strip())
            if aria_has_popup or aria_controls or any(
                token in text for token in ("modal", "popup", "dialog", "overlay")
            ):
                candidates.append(handle)
        return candidates

    async def _prepare_page(self, page: Any, url: str) -> None:
        # Add explicit timeout to prevent hanging on slow/protected pages
        await page.goto(url, wait_until="domcontentloaded", timeout=int(self.page_timeout_seconds * 1000))

        try:
            await page.wait_for_load_state("networkidle", timeout=self.network_idle_timeout_ms)
        except Exception:
            pass

        try:
            await page.wait_for_function("document.readyState === 'complete'", timeout=self.ready_state_timeout_ms)
        except Exception:
            pass

    async def _inject_mutation_observer(self, page: Any) -> None:
        script = """
            () => {
                if (window.__aconObserverInstalled) {
                    return;
                }
                window.__aconObserverInstalled = true;
                window.__aconMutationLinks = window.__aconMutationLinks || [];
                const seen = new Set(window.__aconMutationLinks);

                const pushLink = (href) => {
                    if (!href || seen.has(href)) {
                        return;
                    }
                    seen.add(href);
                    window.__aconMutationLinks.push(href);
                };

                const observer = new MutationObserver((mutations) => {
                    for (const mutation of mutations) {
                        for (const node of mutation.addedNodes) {
                            if (!node || !node.querySelectorAll) {
                                continue;
                            }
                            if (node.matches && node.matches('a[href]')) {
                                pushLink(node.getAttribute('href'));
                            }
                            const anchors = node.querySelectorAll('a[href]');
                            for (const anchor of anchors) {
                                pushLink(anchor.getAttribute('href'));
                            }
                        }
                    }
                });

                observer.observe(document.documentElement || document.body, {
                    childList: true,
                    subtree: true,
                });
            }
        """
        try:
            await page.evaluate(script)
        except Exception:
            pass

    async def _open_page(self):
        if self._shared_browser is not None:
            context = await self._shared_browser.new_context()
            page = await context.new_page()

            async def _close() -> None:
                with suppress(Exception):
                    await context.close()

            return page, _close

        if _CAMOUFOX_AVAILABLE and AsyncNewBrowser is not None:
            if not _PLAYWRIGHT_AVAILABLE or async_playwright is None:
                raise RuntimeError("Playwright is required for Camoufox")
            playwright = await async_playwright().start()
            browser = await AsyncNewBrowser(playwright, headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            async def _close() -> None:
                with suppress(Exception):
                    await context.close()
                with suppress(Exception):
                    await browser.close()
                with suppress(Exception):
                    await playwright.stop()

            return page, _close

        if not _PLAYWRIGHT_AVAILABLE or async_playwright is None:
            raise RuntimeError("No supported browser backend is available")

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        async def _close() -> None:
            with suppress(Exception):
                await context.close()
            with suppress(Exception):
                await browser.close()
            with suppress(Exception):
                await playwright.stop()

        return page, _close

    @staticmethod
    async def _safe_inner_text(handle: Any) -> str:
        try:
            value = await handle.inner_text()
            return value if isinstance(value, str) else ""
        except Exception:
            return ""

    @staticmethod
    async def _safe_get_attribute(handle: Any, name: str) -> str:
        try:
            value = await handle.get_attribute(name)
            return value if isinstance(value, str) else ""
        except Exception:
            return ""

    @staticmethod
    async def _safe_click(handle: Any) -> bool:
        try:
            await handle.click()
            return True
        except Exception:
            return False

    @staticmethod
    async def _safe_hover(handle: Any) -> bool:
        try:
            await handle.hover()
            return True
        except Exception:
            return False
