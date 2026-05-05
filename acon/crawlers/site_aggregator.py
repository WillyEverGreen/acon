"""Site-level data and signal aggregation for Acon."""

from __future__ import annotations
from typing import Any

def aggregate_site_issues(page_results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate results across multiple pages.
    In Acon, this deduplicates findings and generates a high-level summary.
    """
    total_signals_before_dedup = sum(len(list(page.get("data") or page.get("issues") or [])) for page in page_results)
    
    # Generic deduplication based on signal type and selector/location
    seen_keys = set()
    aggregated_signals = []
    
    for page in page_results:
        data = page.get("data") or page.get("issues") or []
        for signal in list(data):
            signal_type = str(signal.get("type") or signal.get("issue_type") or "unknown")
            location = str(signal.get("selector") or signal.get("url") or "")
            dedup_key = f"{signal_type}:{location}"
            
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                aggregated_signals.append({
                    "type": signal_type,
                    "location": location,
                    "severity": str(signal.get("severity") or "minor"),
                    "description": str(signal.get("description") or ""),
                    "affected_page": str(page.get("url") or "")
                })

    return {
        "aggregated_signals": aggregated_signals,
        "total_signals_before_dedup": total_signals_before_dedup,
        "total_signals_after_dedup": len(aggregated_signals),
    }

def compute_site_score(page_results: list[dict[str, Any]], aggregated_signals: list[dict[str, Any]]) -> float:
    """Compute a global intelligence score for the site."""
    if not page_results:
        return 0.0
    
    success_count = sum(1 for p in page_results if (p.get("fetch_status") or p.get("audit_status")) == "success")
    return round((success_count / len(page_results)) * 100, 2)
