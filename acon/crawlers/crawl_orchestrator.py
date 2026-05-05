"""Phase 6 crawl execution orchestrator for multi-page site intelligence (Acon standalone)."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from .. import config as app_config
from ..utils.failure_taxonomy import DegradedReason, normalize_failure, normalize_reason
from .common import normalize_scan_mode
from .crawler import CrawlQueueEntry, CrawlSession
from .page_selector import LiveDOMLinkExtractor, SelectedLink, select_links_for_enqueue
from .site_aggregator import aggregate_site_issues
from . import orchestrator_utils as utils
from ..utils.persistence import AconPersistence
from ..utils.topology_detector import detect_topology

logger = logging.getLogger(__name__)


FAILURE_ACTIONS: dict[str, str] = {
    DegradedReason.RATE_LIMITED.value: "reduce_concurrency",
    DegradedReason.BOT_WALL.value: "stop_crawl",
    DegradedReason.CSP_BLOCKED.value: "disable_browser_engines",
    DegradedReason.CSP_INJECTION_BLOCKED.value: "disable_browser_engines",
    DegradedReason.CONNECTIVITY_BLOCKED.value: "stop_crawl",
    DegradedReason.RENDER_TIMEOUT.value: "reduce_concurrency",
    DegradedReason.BROWSER_NAV_FAILED.value: "count_failure",
    DegradedReason.EXTRACTION_FAILED.value: "count_failure",
    DegradedReason.ENGINE_ERROR.value: "count_failure",
    DegradedReason.PARTIAL_CONTENT.value: "count_failure",
}

FAILURE_SEVERITY_WEIGHT: dict[str, float] = {
    DegradedReason.BOT_WALL.value: 1.0,
    DegradedReason.CONNECTIVITY_BLOCKED.value: 0.9,
    DegradedReason.BROWSER_NAV_FAILED.value: 0.8,
    DegradedReason.RATE_LIMITED.value: 0.6,
    DegradedReason.CSP_BLOCKED.value: 0.5,
    DegradedReason.CSP_INJECTION_BLOCKED.value: 0.5,
    DegradedReason.RENDER_TIMEOUT.value: 0.4,
    DegradedReason.EXTRACTION_FAILED.value: 0.3,
    DegradedReason.PARTIAL_CONTENT.value: 0.3,
    DegradedReason.ENGINE_ERROR.value: 0.2,
}


FetchCallable = Callable[..., Awaitable[dict[str, Any]]]
EventRecorder = Callable[[str, dict[str, Any]], Any]
SiteCrawlResult = dict[str, Any]


@dataclass(slots=True)
class CrawlConfig:
    max_pages: int = 10
    max_depth: int = 2
    timeout_per_page_s: int = 20
    concurrency: int = 2
    await_enrichment: bool = False
    scan_mode: str = "deep"
    disable_sampling: bool = False
    global_timeout_s: int | None = None
    failure_rate_reduce_threshold: float = 0.30
    failure_rate_stop_threshold: float = 0.30
    avg_page_time_reduce_threshold_s: float | None = None
    adaptive_budget_reduce_ratio: float = 0.40
    min_pages_before_adaptive_budget: int = 3
    low_information_window: int = 3
    low_information_gain_threshold: float = 0.05
    min_pages_before_info_gain_stop: int = 4
    standard_page_skip_budget_threshold: int = 1
    discovery_only: bool = False  # If True, skip fetch_callable and return only topology-priority URLs
    db_path: str | None = None  # SQLite database path for session persistence
    post_process: Callable[[str], Any] | None = None  # Optional callable for extraction (e.g. Trafilatura)

    def normalized(self) -> "CrawlConfig":
        scan_mode = normalize_scan_mode(self.scan_mode)
        _, timeout_max = _timeout_bounds_for_mode(scan_mode)
        timeout_per_page_s = int(self.timeout_per_page_s)
        if timeout_per_page_s <= 0:
            timeout_min, timeout_max_default = _timeout_bounds_for_mode(scan_mode)
            timeout_per_page_s = (timeout_min + timeout_max_default) // 2
        timeout_per_page_s = max(1, min(timeout_per_page_s, timeout_max))

        adaptive_threshold = self.avg_page_time_reduce_threshold_s
        if adaptive_threshold is None:
            adaptive_threshold = float(timeout_per_page_s * 0.85)

        max_pages = max(1, int(self.max_pages))
        max_depth = max(0, int(self.max_depth))

        global_timeout_s = self.global_timeout_s
        if global_timeout_s is None:
            global_timeout_s = int(max(30, min(300, max_pages * timeout_per_page_s)))

        max_allowed_concurrency = 3 if scan_mode == "deep" else 2

        return CrawlConfig(
            max_pages=max_pages,
            max_depth=max_depth,
            timeout_per_page_s=timeout_per_page_s,
            concurrency=max(1, min(int(self.concurrency), max_allowed_concurrency)),
            await_enrichment=bool(self.await_enrichment),
            scan_mode=scan_mode,
            disable_sampling=self.disable_sampling,
            global_timeout_s=max(20, int(global_timeout_s)),
            failure_rate_reduce_threshold=min(max(float(self.failure_rate_reduce_threshold), 0.05), 0.90),
            failure_rate_stop_threshold=min(max(float(self.failure_rate_stop_threshold), 0.10), 0.95),
            avg_page_time_reduce_threshold_s=max(4.0, float(adaptive_threshold)),
            adaptive_budget_reduce_ratio=min(max(float(self.adaptive_budget_reduce_ratio), 0.30), 0.50),
            min_pages_before_adaptive_budget=max(1, int(self.min_pages_before_adaptive_budget)),
            low_information_window=max(2, int(self.low_information_window)),
            low_information_gain_threshold=min(max(float(self.low_information_gain_threshold), 0.01), 0.20),
            min_pages_before_info_gain_stop=max(3, int(self.min_pages_before_info_gain_stop)),
            standard_page_skip_budget_threshold=max(1, int(self.standard_page_skip_budget_threshold)),
            discovery_only=self.discovery_only,
            db_path=self.db_path,
            post_process=self.post_process,
        )


@dataclass(slots=True)
class _ProcessedPage:
    entry: CrawlQueueEntry
    page_result: dict[str, Any]
    selected_links: list[SelectedLink]
    skipped_links: list[dict[str, str]]


class SiteCrawlOrchestrator:
    """Deterministic discovery crawl orchestrator for Acon."""

    def __init__(
        self,
        *,
        fetch_callable: Optional[FetchCallable] = None,
        link_extractor: Optional[LiveDOMLinkExtractor] = None,
        event_recorder: Optional[EventRecorder] = None,
    ) -> None:
        self._fetch_callable = fetch_callable or _default_fetch_callable
        self._link_extractor = link_extractor
        self._event_recorder = event_recorder
        
        # Standalone config defaults
        self._rate_limit_backoff_seconds = 5.0
        self._max_consecutive_failures = 3
        self._csp_static_fallback_enabled = True
        self._bot_wall_immediate_stop = True
        self._browser_engines_enabled = True
        self._current_concurrency = 1
        self._persistence: Optional[AconPersistence] = None

    def register_event_recorder(self, recorder: EventRecorder):
        self._event_recorder = recorder

    async def recommend_targets(self, url: str, budget: int = 50) -> list[str]:
        """
        High-level entry point to use Acon as a 'Brain'.
        Returns a list of high-priority URLs based on topology discovery.
        """
        config = CrawlConfig(
            max_pages=budget,
            discovery_only=True,
            scan_mode="fast"  # Discovery is usually best in fast mode
        )
        result = await self.crawl_site(url, config)
        return [page["url"] for page in result.get("page_summaries", [])]

    async def crawl_site(self, seed_url: str, config: CrawlConfig) -> SiteCrawlResult:
        cfg = config.normalized()
        session = CrawlSession()
        link_extractor = self._link_extractor or LiveDOMLinkExtractor()
        created_extractor = self._link_extractor is None

        start_time = time.perf_counter()
        crawl_deadline = start_time + float(cfg.global_timeout_s or 0)
        crawl_timestamp = utils.utc_now_iso()

        # Initialize persistence if requested
        if cfg.db_path:
            self._persistence = AconPersistence(cfg.db_path)
            await self._persistence.initialize()
            
            # Restore seen URLs to prevent re-crawling
            seen_keys = await self._persistence.get_all_dedup_keys()
            session.seen_urls.update(seen_keys)

        pages_crawled = 0
        pages_failed = 0
        pages_skipped_due_to_failure = 0
        pages_skipped_low_value = 0
        consecutive_failures = 0
        effective_max_pages = cfg.max_pages
        effective_concurrency = max(1, int(cfg.concurrency))
        self._current_concurrency = effective_concurrency
        self._browser_engines_enabled = True
        budget_reduction_events = 0
        early_stop_reason: str | None = None

        page_results: list[dict[str, Any]] = []
        page_durations: list[float] = []
        unique_signal_keys: set[str] = set()
        recent_signal_additions: deque[int] = deque(maxlen=cfg.low_information_window)

        seed_enqueued, seed_dedup_key = session.enqueue(
            fetch_url=seed_url,
            depth=0,
            page_type="homepage",
            page_weight=1.0,
            parent_url=None
        )
        if seed_enqueued and self._persistence:
            await self._persistence.save_queue_entry(
                seed_url,
                seed_dedup_key,
                0,
                "homepage",
                1.0
            )

        if not seed_enqueued:
            # Check if we are resuming from persistence
            if self._persistence:
                pending = await self._persistence.get_pending_entries()
                for p in pending:
                    session.enqueue(
                        fetch_url=p["fetch_url"],
                        depth=p["depth"],
                        page_type=p["page_type"],
                        page_weight=p["page_weight"],
                    )
                
                if not session.has_pending:
                    raise ValueError(f"Invalid seed_url and no pending session to resume: {seed_url}")
                
                # Perform early topology detection if we have enough URLs
                all_urls = [p["fetch_url"] for p in pending]
                if len(all_urls) > 1:
                    topology_result = detect_topology(all_urls)
                    session.update_topology(topology_result.topology.value)
                    logger.info(f"Restored session topology: {session.topology}")
            else:
                raise ValueError(f"Invalid seed_url for crawl: {seed_url}")

        await self._emit_event(
            "crawl_started",
            {
                "site_url": seed_url,
                "max_pages": effective_max_pages,
                "max_depth": cfg.max_depth,
                "timeout_per_page_s": cfg.timeout_per_page_s,
                "global_timeout_s": cfg.global_timeout_s,
                "scan_mode": cfg.scan_mode,
                "timestamp": crawl_timestamp,
            },
        )

        if created_extractor:
            await link_extractor.start()

        try:
            while session.has_pending and pages_crawled < effective_max_pages:
                if time.perf_counter() >= crawl_deadline:
                    early_stop_reason = "global_timeout"
                    break

                failure_rate = utils.safe_ratio(pages_failed, pages_crawled)
                if pages_crawled >= 2 and failure_rate >= cfg.failure_rate_stop_threshold:
                    early_stop_reason = "failure_threshold"
                    break

                if failure_rate > cfg.failure_rate_reduce_threshold and effective_concurrency > 1:
                    effective_concurrency = max(1, effective_concurrency - 1)
                    self._current_concurrency = effective_concurrency

                if consecutive_failures >= self._max_consecutive_failures:
                    early_stop_reason = "failure_threshold"
                    break

                batch, skipped_depth_entries = self._dequeue_batch(
                    session=session,
                    cfg=cfg,
                    pages_crawled=pages_crawled,
                    max_pages_limit=effective_max_pages,
                    effective_concurrency=effective_concurrency,
                )

                if not batch:
                    if skipped_depth_entries:
                        continue
                    break

                processed_batch = await asyncio.gather(
                    *[
                        self._process_entry(
                            entry=entry,
                            seed_url=seed_url,
                            timeout_per_page_s=utils.timeout_for_page_type(
                                page_type=entry.page_type,
                                scan_mode=cfg.scan_mode,
                                fallback_timeout_s=cfg.timeout_per_page_s,
                            ),
                            scan_mode=cfg.scan_mode,
                            await_enrichment=cfg.await_enrichment,
                            link_extractor=link_extractor,
                            browser_engines_enabled=self._browser_engines_enabled,
                            disable_sampling=cfg.disable_sampling,
                            discovery_only=cfg.discovery_only,
                            js_required=entry.js_required,
                            post_process=cfg.post_process
                        )
                        for entry in batch
                    ]
                )

                if self._persistence:
                    for entry in batch:
                        await self._persistence.mark_status(entry.fetch_url, "processing")

                # Ensure deterministic processing order regardless of which task finished first
                processed_batch = sorted(processed_batch, key=lambda x: x.entry.fetch_url)
                
                stop_requested = False
                for processed in processed_batch:
                    entry = processed.entry
                    page_results.append(processed.page_result)
                    pages_crawled += 1

                    fetch_status = str(processed.page_result.get("fetch_status") or "error")
                    page_duration_s = float(processed.page_result.get("fetch_duration_s") or 0.0)
                    page_durations.append(page_duration_s)

                    if fetch_status == "success":
                        new_signals = utils.count_new_unique_signals(processed.page_result, unique_signal_keys)
                        recent_signal_additions.append(new_signals)
                        consecutive_failures = 0
                        processed.page_result["failure_reason"] = None
                        processed.page_result["adaptive_action"] = "continue"
                        
                        if self._persistence:
                            await self._persistence.mark_status(entry.fetch_url, "completed")
                            await self._persistence.save_result(entry.fetch_url, processed.page_result)

                        # FIDELITY ESCALATION: If page had 0 data signals but returned links, 
                        # it might be a SPA that needs JS for content.
                        if (
                            not entry.js_required 
                            and len(processed.selected_links) > 0 
                            and len(processed.page_result.get("data") or []) == 0
                            and pages_crawled < effective_max_pages
                        ):
                            logger.info(f"Escalating fidelity for {entry.fetch_url} (Links found via JS, but data empty)")
                            session.enqueue(
                                fetch_url=entry.fetch_url,
                                depth=entry.depth,
                                page_type=entry.page_type,
                                page_weight=entry.page_weight,
                                parent_url=entry.parent_url,
                                js_required=True,
                                fidelity_retry_count=entry.fidelity_retry_count + 1
                            )
                    else:
                        pages_failed += 1
                        normalized_failure = normalize_failure(processed.page_result.get("failure_reason")).value
                        processed.page_result["failure_reason"] = normalized_failure
                        adaptive_action = await self._apply_failure_action(
                            normalized_failure,
                            consecutive_failures,
                        )
                        processed.page_result["adaptive_action"] = adaptive_action

                        if self._persistence:
                            await self._persistence.mark_status(entry.fetch_url, f"failed:{normalized_failure}")

                        if adaptive_action == "stop":
                            stop_requested = True
                            if early_stop_reason is None:
                                early_stop_reason = f"non_recoverable:{normalized_failure}"
                        elif adaptive_action == "slow_down":
                            effective_concurrency = self._current_concurrency
                            await asyncio.sleep(self._rate_limit_backoff_seconds)
                        elif adaptive_action == "static_only":
                            self._browser_engines_enabled = False
                        else:
                            consecutive_failures += 1

                    await self._emit_event(
                        "page_crawled",
                        {
                            "url": entry.fetch_url,
                            "fetch_status": processed.page_result.get("fetch_status"),
                            "duration_s": processed.page_result.get("fetch_duration_s"),
                        },
                    )

                    if fetch_status != "success":
                        pages_skipped_due_to_failure += len(processed.selected_links)
                    else:
                        for link in processed.selected_links:
                            remaining_budget = max(0, effective_max_pages - pages_crawled)
                            if (
                                link.page_type == "standard"
                                and remaining_budget <= cfg.standard_page_skip_budget_threshold
                                and not cfg.disable_sampling
                            ):
                                pages_skipped_low_value += 1
                                continue

                            enqueued, dedup_key = session.enqueue(
                                fetch_url=link.fetch_url,
                                depth=entry.depth + 1,
                                page_type=link.page_type,
                                page_weight=link.page_weight,
                                parent_url=entry.fetch_url
                            )
                            if enqueued and self._persistence:
                                await self._persistence.save_queue_entry(
                                    link.fetch_url,
                                    dedup_key,
                                    entry.depth + 1,
                                    link.page_type,
                                    link.page_weight
                                )

                    if pages_crawled >= cfg.min_pages_before_adaptive_budget:
                        failure_rate = utils.safe_ratio(pages_failed, pages_crawled)
                        avg_page_time = utils.safe_mean(page_durations)
                        if (
                            failure_rate > cfg.failure_rate_reduce_threshold
                            or avg_page_time > float(cfg.avg_page_time_reduce_threshold_s or 0.0)
                        ):
                            remaining_budget = max(0, effective_max_pages - pages_crawled)
                            if remaining_budget > 1:
                                retained_budget = max(
                                    1,
                                    int(round(remaining_budget * (1.0 - cfg.adaptive_budget_reduce_ratio))),
                                )
                                updated_limit = pages_crawled + retained_budget
                                if updated_limit < effective_max_pages:
                                    effective_max_pages = updated_limit
                                    budget_reduction_events += 1

                    if (
                        pages_crawled >= cfg.min_pages_before_info_gain_stop
                        and len(recent_signal_additions) == cfg.low_information_window
                    ):
                        recent_added = sum(recent_signal_additions)
                        total_unique = len(unique_signal_keys)
                        information_gain = recent_added / float(max(1, total_unique))
                        if information_gain < cfg.low_information_gain_threshold:
                            early_stop_reason = "low_information_gain"
                            break

                    if pages_crawled >= effective_max_pages or stop_requested:
                        break
                    
                    # On-the-fly topology detection to refine prioritization
                    if session.topology == "UNKNOWN" and pages_crawled >= 1 and session.pending_count() >= 5:
                        all_pending_urls = [item[3].fetch_url for item in session._heap]
                        topology_result = detect_topology(all_pending_urls)
                        session.update_topology(topology_result.topology.value)
                        logger.info(f"Detected site topology: {session.topology}. Adjusting priorities.")

                    if time.perf_counter() >= crawl_deadline:
                        early_stop_reason = "global_timeout"
                        break

                if stop_requested or pages_crawled >= effective_max_pages:
                    break

            crawl_duration_s = round(time.perf_counter() - start_time, 3)
            crawl_status = utils.derive_crawl_status(
                early_stop_reason=early_stop_reason,
                pages_failed=pages_failed,
                queue_remaining=session.has_pending,
            )
            
            reflection = self._reflect_on_efficiency(
                pages_crawled, 
                len(unique_signal_keys), 
                pages_failed, 
                early_stop_reason
            )

            result: SiteCrawlResult = {
                "site_url": seed_url,
                "crawl_timestamp": crawl_timestamp,
                "crawl_status": crawl_status,
                "topology": session.topology,
                "pages_crawled": pages_crawled,
                "pages_failed": pages_failed,
                "page_summaries": [
                    {
                        "url": str(page.get("fetch_url") or page.get("url") or ""),
                        "page_type": str(page.get("page_type") or "standard"),
                        "page_weight": float(page.get("page_weight") or 0.7),
                        "fetch_status": str(page.get("fetch_status") or "error"),
                        "failure_reason": page.get("failure_reason"),
                        "parent_url": page.get("parent_url"),
                        "js_required": page.get("js_required", False),
                        "result": page.get("post_process_result")
                    }
                    for page in page_results
                ],
                "crawl_meta": {
                    "max_pages_config": cfg.max_pages,
                    "effective_max_pages": effective_max_pages,
                    "crawl_duration_s": crawl_duration_s,
                    "early_stop_reason": early_stop_reason,
                    "reflection": reflection,
                },
            }

            await self._emit_event("crawl_completed", {"site_url": seed_url, "status": crawl_status})
            return result
        finally:
            if created_extractor:
                await link_extractor.close()

    def _dequeue_batch(
        self,
        *,
        session: CrawlSession,
        cfg: CrawlConfig,
        pages_crawled: int,
        max_pages_limit: int,
        effective_concurrency: int,
    ) -> tuple[list[CrawlQueueEntry], list[CrawlQueueEntry]]:
        skipped_depth_entries: list[CrawlQueueEntry] = []
        entry = session.dequeue_prioritized()
        while entry is not None and entry.depth > cfg.max_depth:
            session.pages_skipped_depth += 1
            skipped_depth_entries.append(entry)
            entry = session.dequeue_prioritized()

        if entry is None:
            return [], skipped_depth_entries

        batch = [entry]
        while (
            len(batch) < effective_concurrency
            and session.has_pending
            and pages_crawled + len(batch) < max_pages_limit
        ):
            next_entry = session.dequeue_prioritized()
            if next_entry is None:
                break
            if next_entry.depth > cfg.max_depth:
                session.pages_skipped_depth += 1
                skipped_depth_entries.append(next_entry)
                continue
            batch.append(next_entry)

        return batch, skipped_depth_entries

    async def _process_entry(
        self,
        *,
        entry: CrawlQueueEntry,
        seed_url: str,
        timeout_per_page_s: int,
        scan_mode: str,
        await_enrichment: bool,
        link_extractor: LiveDOMLinkExtractor,
        browser_engines_enabled: bool,
        disable_sampling: bool = False,
        discovery_only: bool = False,
        js_required: bool = False,
        post_process: Callable[[str], Any] | None = None
    ) -> _ProcessedPage:
        started = time.perf_counter()
        fetch_status = "success"
        failure_reason: str | None = None
        data_signals: list[dict[str, Any]] = []

        if not discovery_only:
            try:
                fetch_result = await asyncio.wait_for(
                    self._fetch_callable(
                        url=entry.fetch_url,
                        scan_mode="fast",
                        max_pages=1,
                        await_enrichment=await_enrichment,
                        js_required=js_required,
                    ),
                    timeout=max(1, int(timeout_per_page_s)),
                )
                fetch_status, failure_reason = utils.classify_fetch_result(fetch_result)
                if fetch_status == "success":
                    data_signals = list(fetch_result.get("data") or fetch_result.get("issues") or [])
            except asyncio.TimeoutError:
                fetch_status = "timeout"
                failure_reason = "timeout_exceeded"
            except Exception as exc:
                fetch_status, failure_reason = utils.classify_exception(exc)
        else:
            # In discovery mode, we skip fetch_callable but must still hit the page 
            # for link extraction. Link extraction handles its own navigation.
            fetch_status = "success"

        duration_s = round(time.perf_counter() - started, 3)
        selected_links: list[SelectedLink] = []
        skipped_links: list[dict[str, str]] = []
        
        if fetch_status == "success":
            try:
                raw_links, html = await link_extractor.extract_links(entry.fetch_url, timeout_per_page_s)
                
                # Execute post-processing if provided
                post_process_result = None
                if post_process and html:
                    try:
                        if inspect.isawaitable(post_process):
                            post_process_result = await post_process(html)
                        else:
                            post_process_result = post_process(html)
                    except Exception as e:
                        logger.error(f"Post-processing failed for {entry.fetch_url}: {e}")
                
                selected_links, skipped_links = select_links_for_enqueue(
                    raw_links,
                    current_fetch_url=entry.fetch_url,
                    seed_url=seed_url,
                    next_depth=entry.depth + 1,
                    disable_sampling=disable_sampling
                )
            except Exception as exc:
                logger.debug("Link extraction failed for %s: %s", entry.fetch_url, exc)

        page_result = {
            "url": entry.fetch_url,
            "fetch_url": entry.fetch_url,
            "depth": entry.depth,
            "page_type": entry.page_type,
            "page_weight": entry.page_weight,
            "fetch_status": fetch_status,
            "failure_reason": failure_reason,
            "data": data_signals,
            "fetch_duration_s": duration_s,
            "parent_url": entry.parent_url,
            "js_required": js_required,
            "post_process_result": post_process_result
        }

        return _ProcessedPage(
            entry=entry,
            page_result=page_result,
            selected_links=selected_links,
            skipped_links=skipped_links,
        )

    async def _apply_failure_action(self, reason: str, consecutive_failures: int) -> str:
        action = FAILURE_ACTIONS.get(reason, "count_failure")
        if action == "reduce_concurrency":
            self._current_concurrency = max(1, self._current_concurrency // 2)
            return "slow_down"
        if action == "stop_crawl":
            return "stop"
        if action == "disable_browser_engines":
            self._browser_engines_enabled = False
            return "static_only"
        return "continue"

    async def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_recorder:
            try:
                maybe = self._event_recorder(event_type, payload)
                if inspect.isawaitable(maybe):
                    await maybe
            except Exception as exc:
                logger.debug("Telemetry emission failed for %s: %s", event_type, exc)

    def _reflect_on_efficiency(self, pages: int, unique_signals: int, failures: int, stop_reason: Optional[str]) -> dict[str, Any]:
        """Perform operational reflection on the crawl performance."""
        efficiency = utils.safe_ratio(unique_signals, pages)
        failure_rate = utils.safe_ratio(failures, pages)
        
        advice = "Continue current strategy."
        if efficiency < 0.1 and pages > 5:
            advice = "Low information gain. Consider more diverse seeds or higher depth."
        if failure_rate > 0.2:
            advice = "High failure rate. Check anti-bot settings or proxy health."
            
        return {
            "intelligence_score": round(efficiency, 3),
            "failure_rate": round(failure_rate, 3),
            "stop_reason": stop_reason,
            "advice": advice
        }


async def _default_fetch_callable(**kwargs: Any) -> dict[str, Any]:
    # Default fetcher for standalone Acon. Returns success with empty data.
    return {"fetch_status": "success", "data": []}


def _timeout_bounds_for_mode(scan_mode: str) -> tuple[int, int]:
    # Placeholder for backward compatibility if needed, though internal refs are updated
    return utils.timeout_bounds_for_mode(scan_mode)
