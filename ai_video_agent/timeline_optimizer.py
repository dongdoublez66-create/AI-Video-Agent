from __future__ import annotations

from copy import deepcopy
from typing import Any


def optimize_timeline(
    timeline: dict[str, Any],
    analysis: dict[str, Any] | None,
    target_duration: int,
) -> dict[str, Any]:
    """Use deterministic editing rules to improve the LLM timeline."""
    optimized = deepcopy(timeline)
    segments = list((analysis or {}).get("segments", []))
    if not segments or not optimized.get("scenes"):
        optimized.setdefault("algorithm_optimization", {"enabled": False, "reason": "no analysis data"})
        return optimized

    by_asset: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        by_asset.setdefault(str(segment.get("asset")), []).append(segment)
    for asset_segments in by_asset.values():
        asset_segments.sort(key=lambda row: row.get("highlight_score", 0), reverse=True)

    used_segment_ids: set[str] = set()
    for scene in optimized["scenes"]:
        if scene.get("asset_type") != "video":
            continue
        candidates = by_asset.get(str(scene.get("asset")), [])
        chosen = choose_segment(candidates, used_segment_ids)
        if not chosen:
            continue
        used_segment_ids.add(chosen["id"])
        scene["start"] = float(chosen["start"])
        scene["duration"] = min(float(scene.get("duration", chosen["duration"])), float(chosen["duration"]))
        scene["duration"] = max(1.0, scene["duration"])
        scene["algorithm_score"] = chosen.get("highlight_score", 0)
        scene["algorithm_usage"] = chosen.get("suggested_usage", "")
        if chosen.get("suggested_usage") == "hook_or_key_moment":
            scene["transition"] = {"type": "cut", "duration": 0.0}

    scenes = optimized["scenes"]
    if scenes:
        hook_index = best_hook_index(scenes)
        if hook_index > 0:
            hook = scenes.pop(hook_index)
            hook["id"] = "scene_01"
            scenes.insert(0, hook)

    optimized["scenes"] = trim_to_target(reindex_scenes(remove_near_duplicates(scenes)), target_duration)
    optimized["algorithm_optimization"] = {
        "enabled": True,
        "method": "lightweight_v1",
        "rules": [
            "prefer high sharpness/motion/audio-energy segments",
            "move strongest hook candidate to the first scene",
            "avoid near-duplicate source ranges",
            "trim total duration toward user target",
        ],
        "target_duration": target_duration,
    }
    return optimized


def choose_segment(candidates: list[dict[str, Any]], used_ids: set[str]) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate.get("id") not in used_ids:
            return candidate
    return candidates[0] if candidates else None


def best_hook_index(scenes: list[dict[str, Any]]) -> int:
    best_index = 0
    best_score = -1.0
    limit = min(len(scenes), 6)
    for index, scene in enumerate(scenes[:limit]):
        score = float(scene.get("algorithm_score", 0))
        if scene.get("algorithm_usage") == "hook_or_key_moment":
            score += 0.15
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def remove_near_duplicates(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for scene in scenes:
        key = (str(scene.get("asset")), int(float(scene.get("start", 0)) // 2))
        if key in seen and scene.get("asset_type") == "video":
            continue
        seen.add(key)
        kept.append(scene)
    return kept or scenes


def trim_to_target(scenes: list[dict[str, Any]], target_duration: int) -> list[dict[str, Any]]:
    if not scenes:
        return scenes
    target = max(3.0, float(target_duration))
    total = sum(float(scene.get("duration", 0)) for scene in scenes)
    if total <= target * 1.12:
        return scenes

    trimmed = deepcopy(scenes)
    while sum(float(scene.get("duration", 0)) for scene in trimmed) > target and len(trimmed) > 1:
        weakest_index = weakest_scene_index(trimmed)
        if weakest_index == 0 and len(trimmed) > 1:
            weakest_index = 1
        removed = trimmed.pop(weakest_index)
        if float(removed.get("algorithm_score", 1)) >= 0.55:
            trimmed.append(removed)
            break

    total = sum(float(scene.get("duration", 0)) for scene in trimmed)
    if total > target:
        overflow = total - target
        for scene in reversed(trimmed):
            duration = float(scene.get("duration", 0))
            reducible = max(0.0, duration - 1.2)
            take = min(reducible, overflow)
            scene["duration"] = round(duration - take, 3)
            overflow -= take
            if overflow <= 0.05:
                break
    return reindex_scenes(trimmed)


def weakest_scene_index(scenes: list[dict[str, Any]]) -> int:
    weakest_index = 0
    weakest_score = 999.0
    for index, scene in enumerate(scenes):
        score = float(scene.get("algorithm_score", 0.45))
        if scene.get("asset_type") != "video":
            score += 0.1
        if score < weakest_score:
            weakest_score = score
            weakest_index = index
    return weakest_index


def reindex_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, scene in enumerate(scenes, start=1):
        scene["id"] = f"scene_{index:02d}"
    return scenes


def compact_analysis_for_prompt(analysis: dict[str, Any] | None, limit: int = 18) -> list[dict[str, Any]]:
    if not analysis:
        return []
    top = list(analysis.get("top_segments") or [])
    if not top:
        top = sorted(
            analysis.get("segments", []),
            key=lambda row: row.get("highlight_score", 0),
            reverse=True,
        )[:limit]
    compact = []
    for row in top[:limit]:
        compact.append(
            {
                "asset_index": row.get("asset_index"),
                "asset_name": row.get("asset_name"),
                "start": row.get("start"),
                "duration": row.get("duration"),
                "highlight_score": row.get("highlight_score"),
                "sharpness_score": row.get("sharpness_score"),
                "motion_score": row.get("motion_score"),
                "audio_energy": row.get("audio_energy"),
                "suggested_usage": row.get("suggested_usage"),
            }
        )
    return compact
