"""Internal utilities for the crawl orchestrator."""

from datetime import datetime, timezone
from typing import Any, Optional
from .common import normalize_scan_mode
from ..utils.failure_taxonomy import DegradedReason, normalize_failure

def classify_exception(exc: Exception) -> tuple[str, str]:
    reason = normalize_failure(exc).value
    if reason == DegradedReason.RENDER_TIMEOUT.value:
        return "timeout", reason
    if reason == DegradedReason.BOT_WALL.value:
        return "blocked", reason
    return "error", reason

def classify_fetch_result(fetch_result: dict[str, Any]) -> tuple[str, str | None]:
    if not isinstance(fetch_result, dict):
        return "error", DegradedReason.ENGINE_ERROR.value
    status = fetch_result.get("fetch_status") or fetch_result.get("audit_status") or "success"
    reason = fetch_result.get("failure_reason")
    return status, reason

def timeout_bounds_for_mode(scan_mode: str) -> tuple[int, int]:
    mode = normalize_scan_mode(scan_mode)
    if mode == "fast":
        return 8, 10
    return 12, 15

def timeout_for_page_type(*, page_type: str, scan_mode: str, fallback_timeout_s: int) -> int:
    lowered_page_type = str(page_type or "").strip().lower()
    if lowered_page_type in {"homepage", "interaction", "nav"}:
        timeout_min, timeout_max = 12, 15
    else:
        timeout_min, timeout_max = 8, 10
    return max(1, min(fallback_timeout_s, timeout_max))

def count_new_unique_signals(page_result: dict[str, Any], seen_signal_keys: set[str]) -> int:
    fresh_count = 0
    data = page_result.get("data") or page_result.get("issues") or []
    for item in list(data):
        key = "|".join([str(item.get("type") or item.get("issue_type")), str(item.get("selector"))])
        if key not in seen_signal_keys:
            seen_signal_keys.add(key)
            fresh_count += 1
    return fresh_count

def safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator > 0 else 0.0

def safe_mean(values: list[float]) -> float:
    return float(sum(values)) / float(len(values)) if values else 0.0

def derive_crawl_status(*, early_stop_reason: str | None, pages_failed: int, queue_remaining: bool) -> str:
    if early_stop_reason in {"failure_threshold", "global_timeout"}:
        return "aborted"
    return "completed" if not queue_remaining else "partial"

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
