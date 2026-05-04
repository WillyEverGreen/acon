"""Telemetry collection, sliding-window metrics, and Prometheus rendering."""

from __future__ import annotations

import json
import math
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.failure_taxonomy import classify_failure_reason, normalize_failure
from config import CACHE_STATS, settings

_WINDOW_LOCK = threading.RLock()
_AUDIT_WINDOW: deque[dict[str, Any]] = deque(maxlen=max(10, int(getattr(settings, "metrics_window_size", 1000) or 1000)))
_LLM_FAILURE_TIMESTAMPS: deque[float] = deque(maxlen=5000)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _telemetry_path() -> Path:
    logs_dir = Path(getattr(settings, "logs_dir", "./logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / str(getattr(settings, "telemetry_filename", "telemetry.jsonl"))


def _append_jsonl(payload: dict[str, Any]) -> None:
    path = _telemetry_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])

    ordered = sorted(float(v) for v in values)
    rank = (len(ordered) - 1) * p
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    weight = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _enrichment_breakdown(issues: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {
        "llm": 0,
        "llm_cache": 0,
        "fix_cache": 0,
        "rule_fallback": 0,
        "other": 0,
    }
    for issue in issues:
        source = str(issue.get("_enrichment_source") or issue.get("enrichment_source") or "other")
        if source == "fix_library_cache":
            source = "fix_cache"
        if source.startswith("rule_fallback"):
            source = "rule_fallback"
        if source in buckets:
            buckets[source] += 1
        else:
            buckets["other"] += 1
    return buckets


def _severity_breakdown(issues: list[dict[str, Any]], audit_result: dict[str, Any]) -> dict[str, int]:
    breakdown = {"critical": 0, "major": 0, "minor": 0}
    result_breakdown = audit_result.get("severity_breakdown")
    if isinstance(result_breakdown, dict):
        for key in breakdown:
            if key in result_breakdown:
                breakdown[key] = int(result_breakdown.get(key, 0) or 0)
        return breakdown

    for issue in issues:
        severity = str(issue.get("priority_severity") or issue.get("severity") or "minor").lower()
        if severity == "critical":
            breakdown["critical"] += 1
        elif severity in {"major", "serious"}:
            breakdown["major"] += 1
        else:
            breakdown["minor"] += 1
    return breakdown


def _priority_distribution(issues: list[dict[str, Any]], audit_result: dict[str, Any]) -> dict[str, float]:
    if isinstance(audit_result.get("priority_score_distribution"), dict):
        payload = dict(audit_result.get("priority_score_distribution") or {})
        return {
            "min": float(payload.get("min", 0.0) or 0.0),
            "p50": float(payload.get("p50", 0.0) or 0.0),
            "p95": float(payload.get("p95", 0.0) or 0.0),
            "max": float(payload.get("max", 0.0) or 0.0),
            "avg": float(payload.get("avg", 0.0) or 0.0),
        }

    scores = [float(issue.get("priority_score", 0.0) or 0.0) for issue in issues]
    if not scores:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0, "avg": 0.0}

    ordered = sorted(scores)

    def _percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return float(values[0])
        rank = (len(values) - 1) * p
        lower = math.floor(rank)
        upper = math.ceil(rank)
        if lower == upper:
            return float(values[int(rank)])
        weight = rank - lower
        return float(values[lower] + (values[upper] - values[lower]) * weight)

    return {
        "min": round(float(ordered[0]), 3),
        "p50": round(_percentile(ordered, 0.5), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "max": round(float(ordered[-1]), 3),
        "avg": round(sum(scores) / len(scores), 3),
    }


def _top_issue_types(issues: list[dict[str, Any]], audit_result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(audit_result.get("top_issue_types"), list):
        return list(audit_result.get("top_issue_types") or [])

    counts: dict[str, int] = {}
    for issue in issues:
        issue_type = str(issue.get("issue_type") or "unknown")
        counts[issue_type] = counts.get(issue_type, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"issue_type": issue_type, "count": count} for issue_type, count in ranked[:5]]


def _build_audit_event(audit_result: dict[str, Any], *, status: str) -> dict[str, Any]:
    issues = list(audit_result.get("issues") or [])
    breakdown = _enrichment_breakdown(issues)
    total_enriched = max(1, sum(breakdown.values()))
    fallback_rate = float(breakdown["rule_fallback"]) / float(total_enriched)
    severity_breakdown = _severity_breakdown(issues, audit_result)
    priority_distribution = _priority_distribution(issues, audit_result)
    top_issue_types = _top_issue_types(issues, audit_result)

    score_distribution = audit_result.get("score_distribution")
    if not isinstance(score_distribution, dict):
        score_distribution = {
            "overall_score": float(audit_result.get("score") or 0.0),
            "critical_penalty": 0.0,
            "major_penalty": 0.0,
            "minor_penalty": 0.0,
            "issue_count": int(audit_result.get("total_issues") or 0),
        }

    degraded_reason = normalize_failure(audit_result.get("degraded_reason")).value if audit_result.get("degraded_reason") else ""
    if not degraded_reason and bool(audit_result.get("degraded_mode")):
        degraded_reason = normalize_failure(
            classify_failure_reason(audit_result.get("degradation_reason") or audit_result.get("summary"))
        ).value

    timeout_flag = bool(
        not audit_result.get("quality_gates", {}).get("runtime_passed", True)
        or "timed out" in str(audit_result.get("summary", "")).lower()
    )

    event = {
        "audit_id": str(audit_result.get("audit_id") or ""),
        "timestamp": _utc_now_iso(),
        "event_type": "audit",
        "status": status,
        "url": str(audit_result.get("url") or ""),
        "scan_mode": str(audit_result.get("scan_mode") or "fast"),
        "pages_discovered": int(audit_result.get("pages_discovered") or 1),
        "pages_audited": int(audit_result.get("pages_audited") or 1),
        "scan_time_seconds": float(audit_result.get("scan_time_seconds") or 0.0),
        "total_duration_ms": int(float(audit_result.get("scan_time_seconds") or 0.0) * 1000),
        "degraded_mode": bool(audit_result.get("degraded_mode", False)),
        "timeout": timeout_flag,
        "site_score": float(audit_result.get("score") or 0.0),
        "overall_score": float(audit_result.get("overall_score") or audit_result.get("score") or 0.0),
        "total_issues": int(audit_result.get("total_issues") or 0),
        "critical_issues": severity_breakdown.get("critical", 0),
        "degraded_reason": normalize_failure(degraded_reason).value if degraded_reason else "",
        "severity_counts": severity_breakdown,
        "score_distribution": score_distribution,
        "overall_score_distribution": score_distribution,
        "priority_score_distribution": priority_distribution,
        "top_issue_types": top_issue_types,
        "enrichment_status": str(audit_result.get("enrichment_status") or "complete"),
        "enrichment_source_breakdown": breakdown,
        "enrichment_fallback_rate": round(fallback_rate, 6),
        "engines_used": list(audit_result.get("engines_used") or []),
        "quality_gates": dict(audit_result.get("quality_gates") or {}),
        "cache_counters": dict(CACHE_STATS),
    }
    return event


def record_audit_event(audit_result: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
    """Persist telemetry and register audit metrics in the sliding window."""
    event = _build_audit_event(audit_result, status=status)
    with _WINDOW_LOCK:
        _AUDIT_WINDOW.append(event)
        _append_jsonl(event)
    return event


def record_operational_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist non-audit operational telemetry events to the Phase 0 telemetry stream."""
    event = {
        "timestamp": _utc_now_iso(),
        "event_type": str(event_type or "operational"),
    }
    if isinstance(payload, dict):
        event.update(payload)

    with _WINDOW_LOCK:
        _append_jsonl(event)

    return event


def record_llm_failure(reason: str) -> None:
    """Track LLM failure timestamps for burst alerting."""
    now_ts = datetime.now(timezone.utc).timestamp()
    with _WINDOW_LOCK:
        _LLM_FAILURE_TIMESTAMPS.append(now_ts)
        _append_jsonl(
            {
                "timestamp": _utc_now_iso(),
                "event_type": "llm_failure",
                "reason": str(reason or "unknown"),
            }
        )


def get_llm_failure_count(window_seconds: int) -> int:
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - max(1, int(window_seconds))
    with _WINDOW_LOCK:
        while _LLM_FAILURE_TIMESTAMPS and _LLM_FAILURE_TIMESTAMPS[0] < cutoff:
            _LLM_FAILURE_TIMESTAMPS.popleft()
        return len(_LLM_FAILURE_TIMESTAMPS)


def get_window_events() -> list[dict[str, Any]]:
    with _WINDOW_LOCK:
        return list(_AUDIT_WINDOW)


def _cache_hit_rate(prefix: str) -> float:
    hits = int(CACHE_STATS.get(f"{prefix}_hits", 0) or 0)
    misses = int(CACHE_STATS.get(f"{prefix}_misses", 0) or 0)
    total = hits + misses
    return (float(hits) / float(total)) if total > 0 else 0.0


def get_alert_snapshot() -> dict[str, float]:
    events = get_window_events()
    if not events:
        return {
            "timeout_rate": 0.0,
            "degraded_rate": 0.0,
            "enrichment_fallback_rate": 0.0,
        }

    total = float(len(events))
    timeout_rate = sum(1 for e in events if bool(e.get("timeout"))) / total
    degraded_rate = sum(1 for e in events if bool(e.get("degraded_mode"))) / total
    fallback_rate = sum(float(e.get("enrichment_fallback_rate", 0.0) or 0.0) for e in events) / total

    return {
        "timeout_rate": timeout_rate,
        "degraded_rate": degraded_rate,
        "enrichment_fallback_rate": fallback_rate,
    }


def render_prometheus_metrics() -> str:
    events = get_window_events()

    durations_by_mode: dict[str, list[float]] = {"fast": [], "deep": [], "max": []}
    pages_by_mode: dict[str, list[float]] = {"fast": [], "deep": [], "max": []}

    for e in events:
        mode = str(e.get("scan_mode") or "fast").lower()
        if mode not in durations_by_mode:
            continue
        durations_by_mode[mode].append(float(e.get("total_duration_ms", 0.0) or 0.0))
        pages_by_mode[mode].append(float(e.get("pages_audited", 0.0) or 0.0))

    snapshot = get_alert_snapshot()
    timeout_rate = snapshot["timeout_rate"]
    degraded_rate = snapshot["degraded_rate"]
    fallback_rate = snapshot["enrichment_fallback_rate"]

    total_events = max(1, len(events))
    enrichment_completion_rate = sum(
        1 for e in events if str(e.get("enrichment_status", "")).lower() == "complete"
    ) / float(total_events)

    lines: list[str] = []

    for mode in ("fast", "deep", "max"):
        values = durations_by_mode[mode]
        lines.append(f'acon_audit_duration_p50_ms{{mode="{mode}"}} {_percentile(values, 0.50):.2f}')
        lines.append(f'acon_audit_duration_p95_ms{{mode="{mode}"}} {_percentile(values, 0.95):.2f}')
        lines.append(f'acon_pages_per_audit_p50{{mode="{mode}"}} {_percentile(pages_by_mode[mode], 0.50):.2f}')

    lines.append(f"acon_timeout_rate {timeout_rate:.6f}")
    lines.append(f"acon_degraded_rate {degraded_rate:.6f}")
    lines.append(f"acon_enrichment_completion_rate {enrichment_completion_rate:.6f}")
    lines.append(f"acon_enrichment_fallback_rate {fallback_rate:.6f}")

    lines.append(f'acon_cache_hit_rate{{tier="page"}} {_cache_hit_rate("page"):.6f}')
    lines.append(f'acon_cache_hit_rate{{tier="dom"}} {_cache_hit_rate("dom"):.6f}')
    lines.append(f'acon_cache_hit_rate{{tier="llm"}} {_cache_hit_rate("llm"):.6f}')
    lines.append(f'acon_cache_hit_rate{{tier="fix"}} {_cache_hit_rate("fix"):.6f}')

    # These crawler metrics are placeholders until site-mode runner populates them.
    # Keep explicit gauges so dashboards remain stable.
    lines.append("acon_crawler_sitemap_success_rate 0.000000")
    lines.append("acon_crawler_discovery_fallback_rate 0.000000")

    return "\n".join(lines) + "\n"
