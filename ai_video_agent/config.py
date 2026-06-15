from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


@dataclass(frozen=True)
class ExportPreset:
    name: str
    width: int
    height: int
    fps: int
    video_bitrate: str
    audio_bitrate: str


PRESETS = {
    "douyin": ExportPreset("douyin", 1080, 1920, 30, "8M", "192k"),
    "moments": ExportPreset("moments", 1080, 1920, 30, "6M", "160k"),
    "lecture": ExportPreset("lecture", 1920, 1080, 30, "6M", "160k"),
}


PROJECT_DIRS = [
    "assets/music",
    "assets/sfx",
    "assets/fonts",
    "assets/stickers",
    "inputs/videos",
    "inputs/images",
    "inputs/scripts",
    "outputs/rough_cuts",
    "outputs/finals",
    "outputs/logs",
    "subtitles",
    "timelines",
    "workspace/cache",
    "workspace/manifests",
]

