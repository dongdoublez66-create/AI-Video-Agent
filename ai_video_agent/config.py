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
    "outputs/images",
    "outputs/logs",
    "subtitles",
    "timelines",
    "workspace/cache",
    "workspace/manifests",
    "workspace/runs",
    "models",
]


BASE_IMAGE_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
IP_ADAPTER_MODEL_ID = "h94/IP-Adapter"
IP_ADAPTER_SUBFOLDER = "sdxl_models"
IP_ADAPTER_WEIGHT_NAME = "ip-adapter-plus_sdxl_vit-h.safetensors"
CONTROLNET_MODEL_ID = "diffusers/controlnet-canny-sdxl-1.0"

DEFAULT_IMAGE_STEPS = 25
DEFAULT_GUIDANCE_SCALE = 6.5
DEFAULT_IP_ADAPTER_SCALE = 0.6
CONTROLNET_CANNY_LOW = 100
CONTROLNET_CANNY_HIGH = 200
DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, deformed anatomy, extra limbs, bad hands, duplicate subjects, "
    "messy composition, text, watermark, logo, jpeg artifacts, oversaturated, photorealistic when artwork is requested"
)
