from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


LogFn = Callable[[str], None]

FRAME_WIDTH = 160
FRAME_HEIGHT = 90
FRAME_BYTES = FRAME_WIDTH * FRAME_HEIGHT


def analyze_video_segments(
    manifest: dict[str, Any],
    output_dir: Path,
    target_duration: int,
    log: LogFn = print,
) -> dict[str, Any]:
    """Create lightweight, deterministic video scores for editing decisions."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "method": "lightweight_v1",
            "available": False,
            "reason": "FFmpeg not found",
            "segments": [],
        }

    all_segments: list[dict[str, Any]] = []
    for asset_index, video in enumerate(manifest.get("videos", []), start=1):
        duration = media_duration(video)
        if duration <= 0:
            duration = 4.0
        starts = segment_starts(duration, target_duration)
        log(f"算法分析：{video.get('name', 'video')}，候选片段 {len(starts)} 个")
        for scene_index, start in enumerate(starts, start=1):
            segment_duration = min(4.0, max(1.0, duration - start))
            metrics = score_segment(ffmpeg, Path(video["path"]), start, segment_duration)
            highlight_score = weighted_score(metrics)
            all_segments.append(
                {
                    "id": f"asset_{asset_index:02d}_seg_{scene_index:03d}",
                    "asset_index": asset_index,
                    "asset_type": "video",
                    "asset": video["path"],
                    "asset_name": video.get("name", ""),
                    "start": round(start, 3),
                    "end": round(min(duration, start + segment_duration), 3),
                    "duration": round(segment_duration, 3),
                    "sharpness_score": metrics["sharpness_score"],
                    "motion_score": metrics["motion_score"],
                    "audio_energy": metrics["audio_energy"],
                    "brightness_score": metrics["brightness_score"],
                    "contrast_score": metrics["contrast_score"],
                    "highlight_score": highlight_score,
                    "suggested_usage": suggested_usage(metrics, highlight_score),
                }
            )

    top_segments = sorted(all_segments, key=lambda row: row["highlight_score"], reverse=True)[:12]
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": "lightweight_v1",
        "available": True,
        "segments": all_segments,
        "top_segments": top_segments,
        "summary": {
            "video_count": len(manifest.get("videos", [])),
            "segment_count": len(all_segments),
            "best_score": top_segments[0]["highlight_score"] if top_segments else 0,
        },
    }
    (output_dir / "video_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def segment_starts(duration: float, target_duration: int) -> list[float]:
    if duration <= 5:
        return [0.0]
    max_segments = max(6, min(36, int(target_duration * 1.5)))
    step = 4.0
    if duration / step > max_segments:
        step = duration / max_segments
    starts = []
    cursor = 0.0
    while cursor < max(0.1, duration - 0.75) and len(starts) < max_segments:
        starts.append(round(cursor, 3))
        cursor += step
    return starts or [0.0]


def score_segment(ffmpeg: str, video_path: Path, start: float, duration: float) -> dict[str, float]:
    first = read_gray_frame(ffmpeg, video_path, start + min(0.2, duration * 0.1))
    second = read_gray_frame(ffmpeg, video_path, start + min(duration * 0.65, max(0.2, duration - 0.1)))
    if not first:
        return {
            "sharpness_score": 0.0,
            "motion_score": 0.0,
            "audio_energy": audio_energy_score(ffmpeg, video_path, start, duration),
            "brightness_score": 0.0,
            "contrast_score": 0.0,
        }

    brightness, contrast = brightness_contrast(first)
    return {
        "sharpness_score": round(sharpness_score(first), 4),
        "motion_score": round(motion_score(first, second), 4) if second else 0.0,
        "audio_energy": round(audio_energy_score(ffmpeg, video_path, start, duration), 4),
        "brightness_score": round(brightness, 4),
        "contrast_score": round(contrast, 4),
    }


def read_gray_frame(ffmpeg: str, video_path: Path, timestamp: float) -> bytes | None:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(timestamp, 0):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={FRAME_WIDTH}:{FRAME_HEIGHT},format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, timeout=20)
    except Exception:
        return None
    if completed.returncode != 0 or len(completed.stdout) < FRAME_BYTES:
        return None
    return completed.stdout[:FRAME_BYTES]


def brightness_contrast(frame: bytes) -> tuple[float, float]:
    values = frame
    mean = sum(values) / len(values) / 255.0
    variance = sum(((value / 255.0) - mean) ** 2 for value in values) / len(values)
    contrast = math.sqrt(variance)
    brightness_score = clamp(1.0 - abs(mean - 0.52) * 2.0)
    contrast_score = clamp(contrast * 3.2)
    return brightness_score, contrast_score


def sharpness_score(frame: bytes) -> float:
    total = 0
    count = 0
    for y in range(FRAME_HEIGHT):
        base = y * FRAME_WIDTH
        for x in range(FRAME_WIDTH - 1):
            total += abs(frame[base + x] - frame[base + x + 1])
            count += 1
    for y in range(FRAME_HEIGHT - 1):
        base = y * FRAME_WIDTH
        next_base = (y + 1) * FRAME_WIDTH
        for x in range(FRAME_WIDTH):
            total += abs(frame[base + x] - frame[next_base + x])
            count += 1
    return clamp((total / max(count, 1) / 255.0) * 4.2)


def motion_score(first: bytes, second: bytes | None) -> float:
    if not second:
        return 0.0
    total = sum(abs(a - b) for a, b in zip(first, second))
    return clamp((total / len(first) / 255.0) * 3.5)


def audio_energy_score(ffmpeg: str, video_path: Path, start: float, duration: float) -> float:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-ss",
        f"{max(start, 0):.3f}",
        "-t",
        f"{max(duration, 0.5):.3f}",
        "-i",
        str(video_path),
        "-vn",
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
        )
    except Exception:
        return 0.0
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", completed.stderr or "")
    if not match:
        return 0.0
    mean_db = float(match.group(1))
    return clamp((mean_db + 45.0) / 35.0)


def weighted_score(metrics: dict[str, float]) -> float:
    score = (
        metrics.get("sharpness_score", 0) * 0.25
        + metrics.get("motion_score", 0) * 0.25
        + metrics.get("audio_energy", 0) * 0.24
        + metrics.get("brightness_score", 0) * 0.14
        + metrics.get("contrast_score", 0) * 0.12
    )
    return round(clamp(score), 4)


def suggested_usage(metrics: dict[str, float], highlight_score: float) -> str:
    if highlight_score >= 0.72 and metrics.get("motion_score", 0) >= 0.45:
        return "hook_or_key_moment"
    if metrics.get("sharpness_score", 0) >= 0.68 and metrics.get("motion_score", 0) < 0.35:
        return "detail_or_product_shot"
    if metrics.get("audio_energy", 0) >= 0.65:
        return "voice_or_action_moment"
    if highlight_score >= 0.5:
        return "supporting_scene"
    return "bridge_or_low_priority"


def media_duration(item: dict[str, Any]) -> float:
    try:
        return float(item.get("probe", {}).get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def find_ffmpeg() -> str | None:
    local_ffmpeg = Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        return path_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
