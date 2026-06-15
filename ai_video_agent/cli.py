from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    PRESETS,
    PROJECT_DIRS,
    ROOT,
    VIDEO_EXTENSIONS,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-video-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check local editing dependencies.")
    subparsers.add_parser("init", help="Create the standard workspace folders.")
    subparsers.add_parser("gui", help="Launch the Windows desktop agent UI.")

    manifest_parser = subparsers.add_parser("manifest", help="Scan local media assets.")
    manifest_parser.add_argument("--out", default="workspace/manifests/assets.json")

    plan_parser = subparsers.add_parser("plan", help="Create a starter timeline from local assets.")
    plan_parser.add_argument("--brief", default="inputs/scripts/sample_brief.md")
    plan_parser.add_argument("--out", default="timelines/rough_cut.json")
    plan_parser.add_argument("--preset", default="douyin", choices=sorted(PRESETS))

    render_parser = subparsers.add_parser("render", help="Render an MP4 from a timeline.")
    render_parser.add_argument("--timeline", required=True)
    render_parser.add_argument("--output", required=True)

    args = parser.parse_args()

    if args.command == "doctor":
        doctor()
    elif args.command == "init":
        init_workspace()
    elif args.command == "gui":
        from .gui import main as gui_main

        gui_main()
    elif args.command == "manifest":
        write_manifest(Path(args.out))
    elif args.command == "plan":
        create_plan(Path(args.brief), Path(args.out), args.preset)
    elif args.command == "render":
        render_timeline(Path(args.timeline), Path(args.output))


def init_workspace() -> None:
    for folder in PROJECT_DIRS:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    print(f"Workspace ready: {ROOT}")


def doctor() -> None:
    init_workspace()
    ffmpeg = find_ffmpeg()
    checks = {
        "python": sys.executable,
        "ffmpeg": ffmpeg,
        "ffprobe": shutil.which("ffprobe"),
        "imageio_ffmpeg": has_imageio_ffmpeg(),
    }
    print(json.dumps(checks, indent=2, ensure_ascii=False))
    if not checks["ffmpeg"]:
        print("\nFFmpeg is required for rendering.")
        print("Recommended China-friendly install:")
        print("  python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple imageio-ffmpeg")


def scan_assets() -> dict:
    videos = scan_files(ROOT / "inputs/videos", VIDEO_EXTENSIONS)
    images = scan_files(ROOT / "inputs/images", IMAGE_EXTENSIONS)
    music = scan_files(ROOT / "assets/music", AUDIO_EXTENSIONS)
    sfx = scan_files(ROOT / "assets/sfx", AUDIO_EXTENSIONS)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "videos": videos,
        "images": images,
        "music": music,
        "sfx": sfx,
    }


def scan_files(folder: Path, extensions: set[str]) -> list[dict]:
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in extensions:
            items.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "name": path.name,
                    "type": path.suffix.lower().lstrip("."),
                }
            )
    return items


def write_manifest(out_path: Path) -> None:
    init_workspace()
    manifest = scan_assets()
    target = resolve_project_path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote manifest: {target}")


def create_plan(brief_path: Path, out_path: Path, preset_name: str) -> None:
    init_workspace()
    manifest = scan_assets()
    preset = PRESETS[preset_name]
    brief_file = resolve_project_path(brief_path)
    brief = brief_file.read_text(encoding="utf-8") if brief_file.exists() else ""
    clips = manifest["videos"] + manifest["images"]

    scenes = []
    for index, clip in enumerate(clips[:8], start=1):
        scene = {
            "id": f"scene_{index:02d}",
            "asset": clip["path"],
            "duration": 4.0 if clip["path"].lower().split(".")[-1] in {"jpg", "jpeg", "png", "webp", "bmp"} else 5.0,
            "transition": {"type": "fade", "duration": 0.35},
            "caption": f"镜头 {index}",
            "notes": "Codex can replace this with script-aware editing decisions.",
        }
        if clip["path"].lower().split(".")[-1] not in {"jpg", "jpeg", "png", "webp", "bmp"}:
            scene["start"] = 0.0
        scenes.append(scene)

    timeline = {
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "brief": brief.strip(),
        "preset": {
            "name": preset.name,
            "width": preset.width,
            "height": preset.height,
            "fps": preset.fps,
            "video_bitrate": preset.video_bitrate,
            "audio_bitrate": preset.audio_bitrate,
        },
        "background_music": manifest["music"][0]["path"] if manifest["music"] else None,
        "music_volume": 0.18,
        "voiceover": None,
        "scenes": scenes,
        "subtitles": {
            "format": "srt",
            "path": "subtitles/rough_cut.srt",
            "style": "large_white_with_shadow",
        },
    }

    target = resolve_project_path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(timeline, indent=2, ensure_ascii=False), encoding="utf-8")
    write_srt_from_scenes(timeline["scenes"], ROOT / timeline["subtitles"]["path"])
    print(f"Wrote starter timeline: {target}")
    if not scenes:
        print("No input videos/images found yet. Add media to inputs/videos or inputs/images, then run plan again.")


def render_timeline(timeline_path: Path, output_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise SystemExit("ffmpeg was not found. Run `python -m ai_video_agent doctor` for details.")

    timeline_file = resolve_project_path(timeline_path)
    timeline = json.loads(timeline_file.read_text(encoding="utf-8"))
    preset = timeline["preset"]
    cache_dir = ROOT / "workspace/cache/render"
    cache_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = []

    for index, scene in enumerate(timeline.get("scenes", []), start=1):
        asset = ROOT / scene["asset"]
        if not asset.exists():
            raise SystemExit(f"Missing asset: {asset}")
        segment = cache_dir / f"segment_{index:03d}.mp4"
        render_segment(ffmpeg, asset, scene, preset, segment)
        segment_paths.append(segment)

    if not segment_paths:
        raise SystemExit("Timeline has no scenes to render.")

    concat_file = cache_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in segment_paths),
        encoding="utf-8",
    )

    target = resolve_project_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    log_path = ROOT / "outputs/logs" / f"{target.stem}.log"
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
    ]

    music = timeline.get("background_music")
    if music:
        music_path = ROOT / music
        if music_path.exists():
            cmd.extend(["-stream_loop", "-1", "-i", str(music_path)])
            cmd.extend(
                [
                    "-filter_complex",
                    f"[1:a]volume={timeline.get('music_volume', 0.18)}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]",
                    "-map",
                    "0:v",
                    "-map",
                    "[a]",
                ]
            )

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            preset.get("video_bitrate", "8M"),
            "-c:a",
            "aac",
            "-b:a",
            preset.get("audio_bitrate", "192k"),
            "-shortest",
            str(target),
        ]
    )
    run(cmd, log_path)
    print(f"Rendered: {target}")
    print(f"Log: {log_path}")


def render_segment(ffmpeg: str, asset: Path, scene: dict, preset: dict, output: Path) -> None:
    width = int(preset["width"])
    height = int(preset["height"])
    fps = int(preset["fps"])
    duration = float(scene.get("duration", 5.0))
    extension = asset.suffix.lower()
    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1"
    )
    fade = scene.get("transition", {}).get("type") == "fade"
    fade_duration = float(scene.get("transition", {}).get("duration", 0.35))
    filters = [scale_filter, f"fps={fps}"]
    if fade and duration > fade_duration * 2:
        filters.append(f"fade=t=in:st=0:d={fade_duration}")
        filters.append(f"fade=t=out:st={duration - fade_duration}:d={fade_duration}")

    if extension in IMAGE_EXTENSIONS:
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            str(duration),
            "-i",
            str(asset),
            "-f",
            "lavfi",
            "-t",
            str(duration),
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            ",".join(filters),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(output),
        ]
    else:
        cmd = [
            ffmpeg,
            "-y",
            "-ss",
            str(scene.get("start", 0.0)),
            "-t",
            str(duration),
            "-i",
            str(asset),
            "-vf",
            ",".join(filters),
            "-af",
            f"afade=t=in:st=0:d={fade_duration},afade=t=out:st={max(duration - fade_duration, 0)}:d={fade_duration}",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
    run(cmd, ROOT / "outputs/logs" / "segments.log")


def run(cmd: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n\n$ " + " ".join(cmd) + "\n")
        completed = subprocess.run(cmd, stdout=log, stderr=log, text=True)
    if completed.returncode != 0:
        raise SystemExit(f"Command failed. See log: {log_path}")


def write_srt_from_scenes(scenes: list[dict], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cursor = 0.0
    blocks = []
    for index, scene in enumerate(scenes, start=1):
        duration = float(scene.get("duration", 5.0))
        caption = str(scene.get("caption", "")).strip()
        if caption:
            blocks.append(
                "\n".join(
                    [
                        str(index),
                        f"{format_srt_time(cursor)} --> {format_srt_time(cursor + duration)}",
                        caption,
                    ]
                )
            )
        cursor += duration
    target.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")


def format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def find_ffmpeg() -> str | None:
    local_ffmpeg = ROOT / "tools/ffmpeg/bin/ffmpeg.exe"
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


def has_imageio_ffmpeg() -> bool:
    try:
        import imageio_ffmpeg  # noqa: F401

        return True
    except Exception:
        return False
