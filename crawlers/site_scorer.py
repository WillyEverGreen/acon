"""Site-level score computation for Phase 6 crawl outputs."""

from __future__ import annotations

from typing import Any


def compute_site_score(
    page_results: list[dict[str, Any]],
    aggregated_issues: list[dict[str, Any]],
) -> float | None:
    """Compute weighted site score using successful pages and critical penalty cap."""
    successful = [
        row
        for row in page_results
        if str(row.get("audit_status") or "") == "success"
        and isinstance(row.get("score"), (int, float))
    ]
    if not successful:
        return None

    weighted_sum = 0.0
    weight_total = 0.0
    for page in successful:
        weight = float(page.get("page_weight", 0.7) or 0.7)
        score = float(page.get("score", 0.0) or 0.0)
        weighted_sum += score * weight
        weight_total += weight

    if weight_total <= 0:
        return None

    base_site_score = weighted_sum / weight_total

    critical_issue_count = sum(
        1 for issue in aggregated_issues if str(issue.get("severity", "")).lower() == "critical"
    )
    penalty = min(critical_issue_count * 2, 20)

    return round(max(base_site_score - penalty, 0.0), 1)
