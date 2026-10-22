"""Impact × uncertainty review ordering without acceptance gamification."""

from __future__ import annotations


def rank_candidates(items: list[dict]) -> list[dict]:
    ranked: list[dict] = []
    for raw in items:
        item = dict(raw)
        impact = max(0.0, float(item.get("impact", 1.0)))
        confidence = min(1.0, max(0.0, float(item.get("suggestion_confidence", 0.0))))
        score = impact * (1.0 - confidence)
        item["selection_score"] = score
        item["selection_reason"] = f"impact={impact:.3f} × uncertainty={1.0-confidence:.3f}"
        ranked.append(item)
    return sorted(ranked, key=lambda item: (-item["selection_score"], str(item.get("candidate_id", ""))))
