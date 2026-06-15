from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, ROOT, VIDEO_EXTENSIONS
from .llm import LLMConfig, OpenAICompatibleClient


LogFn = Callable[[str], None]


@dataclass(frozen=True)
class EditRequest:
    media_dir: Path
    music_dir: Path | None
    output_dir: Path | None
    output_name: str
    base_url: str
    api_key: str
    model: str
    style: str
    keyframe_notes: str
    focus_notes: str
    target_duration: int
    aspect_ratio: str
    prefer_davinci: bool = True


@dataclass(frozen=True)
class EditResult:
    backend: str
    output_video: Path
    run_dir: Path
    timeline_path: Path
    script_path: Path
    subtitle_path: Path
    report_path: Path


class AgentError(RuntimeError):
    pass


def run_edit(request: EditRequest, log: LogFn = print) -> EditResult:
    started_at = datetime.now()
    slug = safe_slug(request.output_name or f"edit_{started_at:%Y%m%d_%H%M%S}")
    run_dir = ROOT / "workspace" / "runs" / f"{started_at:%Y%m%d_%H%M%S}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "review").mkdir(exist_ok=True)
    (run_dir / "resolve").mkdir(exist_ok=True)
    (run_dir / "ffmpeg").mkdir(exist_ok=True)

    log("正在扫描素材...")
    manifest = scan_media(request.media_dir, request.music_dir)
    if not manifest["videos"] and not manifest["images"]:
        raise AgentError("没有找到可剪辑的视频或图片素材。")
    manifest_path = run_dir / "media_manifest.json"
    write_json(manifest_path, manifest)

    log("正在抽取关键帧...")
    frame_index = extract_review_frames(manifest, run_dir / "review")
    frame_index_path = run_dir / "review" / "frames_index.json"
    write_json(frame_index_path, frame_index)

    log("正在调用大模型生成剪辑脚本和时间线...")
    llm = OpenAICompatibleClient(
        LLMConfig(
            base_url=request.base_url,
            api_key=request.api_key,
            model=request.model,
            timeout_seconds=180,
        )
    )
    plan = create_llm_plan(llm, request, manifest, frame_index)
    plan = normalize_plan(plan, request, manifest)

    timeline = build_timeline(plan, request, manifest)
    script_text = build_script_markdown(plan, timeline, request, manifest)

    timeline_path = ROOT / "timelines" / f"{slug}.json"
    subtitle_path = ROOT / "subtitles" / f"{slug}.srt"
    script_path = ROOT / "outputs" / "logs" / f"{slug}_script.md"
    report_path = run_dir / "agent_report.json"

    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    subtitle_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(timeline_path, timeline)
    subtitle_path.write_text(render_srt(timeline["scenes"]), encoding="utf-8")
    script_path.write_text(script_text, encoding="utf-8")

    output_base_dir = request.output_dir.expanduser().resolve() if request.output_dir else ROOT / "outputs" / "rough_cuts"
    output_video = output_base_dir / f"{slug}.mp4"
    output_video.parent.mkdir(parents=True, exist_ok=True)

    backend = "ffmpeg"
    render_report: dict[str, Any] = {}
    if request.prefer_davinci:
        log("正在尝试连接 DaVinci Resolve...")
        try:
            output_video, render_report = render_with_davinci(timeline, output_video, slug, log)
            backend = "davinci"
        except Exception as exc:
            log(f"DaVinci 自动剪辑失败，切换到 FFmpeg：{exc}")
            output_video, render_report = render_with_ffmpeg(timeline, output_video, run_dir, log)
            backend = "ffmpeg"
    else:
        output_video, render_report = render_with_ffmpeg(timeline, output_video, run_dir, log)

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "backend": backend,
        "request": {
            "media_dir": str(request.media_dir),
            "music_dir": str(request.music_dir) if request.music_dir else "",
            "output_dir": str(output_base_dir),
            "style": request.style,
            "keyframe_notes": request.keyframe_notes,
            "focus_notes": request.focus_notes,
            "target_duration": request.target_duration,
            "aspect_ratio": request.aspect_ratio,
            "model": request.model,
            "base_url": request.base_url,
        },
        "manifest": str(manifest_path),
        "frames": str(frame_index_path),
        "timeline": str(timeline_path),
        "script": str(script_path),
        "subtitles": str(subtitle_path),
        "output_video": str(output_video),
        "render_report": render_report,
    }
    write_json(report_path, report)
    log(f"完成：{output_video}")

    return EditResult(
        backend=backend,
        output_video=output_video,
        run_dir=run_dir,
        timeline_path=timeline_path,
        script_path=script_path,
        subtitle_path=subtitle_path,
        report_path=report_path,
    )


def scan_media(media_dir: Path, music_dir: Path | None) -> dict[str, Any]:
    media_dir = media_dir.expanduser().resolve()
    if not media_dir.exists():
        raise AgentError(f"素材文件夹不存在：{media_dir}")
    videos = scan_files(media_dir, VIDEO_EXTENSIONS, "video")
    images = scan_files(media_dir, IMAGE_EXTENSIONS, "image")
    music = scan_files(music_dir.expanduser().resolve(), AUDIO_EXTENSIONS, "audio") if music_dir and music_dir.exists() else []
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "media_dir": str(media_dir),
        "music_dir": str(music_dir.expanduser().resolve()) if music_dir and music_dir.exists() else "",
        "videos": videos,
        "images": images,
        "music": music,
    }


def scan_files(folder: Path, extensions: set[str], media_type: str) -> list[dict[str, Any]]:
    items = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in extensions:
            info = {
                "path": str(path.resolve()),
                "name": path.name,
                "media_type": media_type,
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
            }
            if media_type in {"video", "audio"}:
                info["probe"] = probe_media(path)
            items.append(info)
    return items


def probe_media(path: Path) -> dict[str, Any]:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return {}
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        return {"error": completed.stderr.strip()}
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def extract_review_frames(manifest: dict[str, Any], review_dir: Path) -> list[dict[str, Any]]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    frames_dir = review_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, video in enumerate(manifest["videos"], start=1):
        duration = media_duration(video)
        timestamps = sample_timestamps(duration)
        for frame_index, timestamp in enumerate(timestamps, start=1):
            output = frames_dir / f"{index:03d}_{frame_index:02d}_{safe_slug(Path(video['name']).stem)}.jpg"
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                video["path"],
                "-frames:v",
                "1",
                "-vf",
                "scale=640:-2",
                "-y",
                str(output),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            rows.append(
                {
                    "source_path": video["path"],
                    "source_name": video["name"],
                    "timestamp_seconds": timestamp,
                    "image_path": str(output),
                    "ok": completed.returncode == 0 and output.exists(),
                }
            )
    return rows


def create_llm_plan(
    llm: OpenAICompatibleClient,
    request: EditRequest,
    manifest: dict[str, Any],
    frame_index: list[dict[str, Any]],
) -> dict[str, Any]:
    media_summary = summarize_media(manifest, frame_index)
    width, height = dimensions_for_aspect(request.aspect_ratio)
    system = (
        "你是一个本地视频剪辑 Agent 的剪辑导演。你必须基于用户素材信息生成可执行 JSON，"
        "不要编造不存在的素材。输出必须是 JSON 对象。"
    )
    user = f"""
请为本地自动剪辑生成方案。

用户想要的风格：
{request.style}

关键帧和重点内容补充：
{request.keyframe_notes}

重点剪辑方式补充：
{request.focus_notes}

目标时长：约 {request.target_duration} 秒
画幅：{request.aspect_ratio}，导出尺寸 {width}x{height}

素材信息：
{json.dumps(media_summary, ensure_ascii=False, indent=2)}

请返回 JSON，格式如下：
{{
  "title": "短标题",
  "summary": "剪辑思路",
  "music_policy": "BGM 使用建议",
  "scenes": [
    {{
      "asset_index": 1,
      "asset_type": "video",
      "start": 0.0,
      "duration": 3.0,
      "caption": "这一段字幕",
      "notes": "为什么这样剪",
      "transition": "fade"
    }}
  ],
  "subtitles": ["字幕1", "字幕2"],
  "delivery_notes": "导出和后期建议"
}}

规则：
- asset_index 从素材信息里的 videos/images 的 index 选择。
- 视频片段 start 和 duration 不要超过素材时长。
- 图片 start 固定 0。
- scenes 总时长接近目标时长，但不要为了凑时长重复无意义镜头。
- 第一段要有钩子，中段要体现重点，结尾要有收束。
- 如果素材少，可以重复使用强镜头，但要说明理由。
- caption 用中文，简短适合短视频。
"""
    return llm.complete_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )


def summarize_media(manifest: dict[str, Any], frame_index: list[dict[str, Any]]) -> dict[str, Any]:
    frames_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in frame_index:
        if row.get("ok"):
            frames_by_source.setdefault(row["source_path"], []).append(
                {
                    "timestamp_seconds": row["timestamp_seconds"],
                    "image_path": row["image_path"],
                }
            )
    return {
        "videos": [
            {
                "index": index,
                "name": item["name"],
                "path": item["path"],
                "duration": media_duration(item),
                "resolution": media_resolution(item),
                "sampled_frames": frames_by_source.get(item["path"], []),
            }
            for index, item in enumerate(manifest["videos"], start=1)
        ],
        "images": [
            {
                "index": index,
                "name": item["name"],
                "path": item["path"],
            }
            for index, item in enumerate(manifest["images"], start=1)
        ],
        "music": [
            {
                "index": index,
                "name": item["name"],
                "path": item["path"],
                "duration": media_duration(item),
            }
            for index, item in enumerate(manifest["music"], start=1)
        ],
    }


def normalize_plan(plan: dict[str, Any], request: EditRequest, manifest: dict[str, Any]) -> dict[str, Any]:
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        plan["scenes"] = fallback_scenes(request, manifest)
    return plan


def fallback_scenes(request: EditRequest, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    assets = [("video", item) for item in manifest["videos"]] + [("image", item) for item in manifest["images"]]
    if not assets:
        return []
    target = max(6, request.target_duration)
    per_scene = max(2.5, min(5.0, target / min(len(assets), 8)))
    scenes = []
    for index, (asset_type, item) in enumerate(assets[:8], start=1):
        duration = per_scene if asset_type == "video" else min(4.0, per_scene)
        available = media_duration(item)
        if asset_type == "video" and available:
            duration = min(duration, max(1.0, available))
        scenes.append(
            {
                "asset_index": index,
                "asset_type": asset_type,
                "start": 0.0,
                "duration": duration,
                "caption": f"镜头 {index}",
                "notes": "自动兜底剪辑点。",
                "transition": "fade",
            }
        )
    return scenes


def build_timeline(plan: dict[str, Any], request: EditRequest, manifest: dict[str, Any]) -> dict[str, Any]:
    width, height = dimensions_for_aspect(request.aspect_ratio)
    fps = 30
    videos = manifest["videos"]
    images = manifest["images"]
    music = manifest["music"]
    scenes = []
    for index, raw_scene in enumerate(plan.get("scenes", []), start=1):
        asset_type = str(raw_scene.get("asset_type", "video")).lower()
        asset_index = int(raw_scene.get("asset_index", 1))
        collection = videos if asset_type == "video" else images
        if not collection:
            continue
        asset_index = min(max(asset_index, 1), len(collection))
        asset = collection[asset_index - 1]
        available = media_duration(asset) if asset_type == "video" else 0
        start = max(0.0, float(raw_scene.get("start", 0.0))) if asset_type == "video" else 0.0
        duration = max(1.0, float(raw_scene.get("duration", 3.0)))
        if asset_type == "video" and available:
            start = min(start, max(0.0, available - 0.25))
            duration = min(duration, max(1.0, available - start))
        scenes.append(
            {
                "id": f"scene_{len(scenes) + 1:02d}",
                "asset": asset["path"],
                "asset_type": asset_type,
                "start": start,
                "duration": duration,
                "transition": {
                    "type": "fade" if str(raw_scene.get("transition", "fade")).lower() != "cut" else "cut",
                    "duration": 0.25,
                },
                "caption": str(raw_scene.get("caption", f"镜头 {index}")).strip() or f"镜头 {index}",
                "notes": str(raw_scene.get("notes", "")).strip(),
            }
        )
    if not scenes:
        for raw_scene in fallback_scenes(request, manifest):
            plan["scenes"] = [raw_scene]
        return build_timeline(plan, request, manifest)

    return {
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "brief": request.style.strip(),
        "agent_plan": plan,
        "preset": {
            "name": "agent_custom",
            "width": width,
            "height": height,
            "fps": fps,
            "video_bitrate": "10M",
            "audio_bitrate": "192k",
        },
        "background_music": music[0]["path"] if music else None,
        "music_volume": 0.18,
        "voiceover": None,
        "scenes": scenes,
        "subtitles": {
            "format": "srt",
            "path": "",
            "style": "large_white_with_shadow",
        },
    }


def build_script_markdown(
    plan: dict[str, Any],
    timeline: dict[str, Any],
    request: EditRequest,
    manifest: dict[str, Any],
) -> str:
    lines = [
        f"# {plan.get('title', request.output_name or 'AI 自动剪辑')}",
        "",
        "## 用户需求",
        "",
        f"- 视频风格：{request.style}",
        f"- 关键帧补充：{request.keyframe_notes}",
        f"- 重点剪辑补充：{request.focus_notes}",
        f"- 目标时长：{request.target_duration} 秒",
        f"- 画幅：{request.aspect_ratio}",
        "",
        "## 剪辑思路",
        "",
        str(plan.get("summary", "根据素材自动组织镜头。")),
        "",
        "## 镜头脚本",
        "",
    ]
    cursor = 0.0
    for scene in timeline["scenes"]:
        end = cursor + float(scene["duration"])
        lines.extend(
            [
                f"### {scene['id']}  {cursor:.2f}s - {end:.2f}s",
                "",
                f"- 素材：{scene['asset']}",
                f"- 字幕：{scene['caption']}",
                f"- 剪辑说明：{scene.get('notes', '')}",
                "",
            ]
        )
        cursor = end
    lines.extend(
        [
            "## 音乐策略",
            "",
            str(plan.get("music_policy", "优先使用用户提供的 BGM，音量保持在 15%-25%。")),
            "",
            "## 交付说明",
            "",
            str(plan.get("delivery_notes", "已输出时间线、字幕、脚本和粗剪视频。")),
            "",
            "## 素材统计",
            "",
            f"- 视频：{len(manifest['videos'])}",
            f"- 图片：{len(manifest['images'])}",
            f"- 音乐：{len(manifest['music'])}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_with_ffmpeg(
    timeline: dict[str, Any],
    output_video: Path,
    run_dir: Path,
    log: LogFn,
) -> tuple[Path, dict[str, Any]]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise AgentError("找不到 FFmpeg。")
    log("正在使用 FFmpeg 渲染...")
    output_video.parent.mkdir(parents=True, exist_ok=True)
    preset = timeline["preset"]
    cache_dir = run_dir / "ffmpeg" / "segments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = []
    for index, scene in enumerate(timeline["scenes"], start=1):
        segment = cache_dir / f"segment_{index:03d}.mp4"
        render_segment_ffmpeg(ffmpeg, scene, preset, segment)
        segment_paths.append(segment)

    concat_file = cache_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in segment_paths),
        encoding="utf-8",
    )
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]
    music = timeline.get("background_music")
    if music and Path(music).exists():
        cmd.extend(["-stream_loop", "-1", "-i", music])
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
            preset.get("video_bitrate", "10M"),
            "-c:a",
            "aac",
            "-b:a",
            preset.get("audio_bitrate", "192k"),
            "-shortest",
            str(output_video),
        ]
    )
    run_command(cmd, ROOT / "outputs" / "logs" / f"{output_video.stem}_ffmpeg.log")
    return output_video, {"backend": "ffmpeg", "segments": [str(path) for path in segment_paths]}


def render_segment_ffmpeg(ffmpeg: str, scene: dict[str, Any], preset: dict[str, Any], output: Path) -> None:
    width = int(preset["width"])
    height = int(preset["height"])
    fps = int(float(preset["fps"]))
    duration = float(scene.get("duration", 3.0))
    asset = Path(scene["asset"])
    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1"
    )
    filters = [scale_filter, f"fps={fps}"]
    transition = scene.get("transition", {})
    fade_duration = float(transition.get("duration", 0.25))
    if transition.get("type") == "fade" and duration > fade_duration * 2:
        filters.append(f"fade=t=in:st=0:d={fade_duration}")
        filters.append(f"fade=t=out:st={duration - fade_duration}:d={fade_duration}")
    if asset.suffix.lower() in IMAGE_EXTENSIONS:
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
    run_command(cmd, ROOT / "outputs" / "logs" / "agent_segments.log")


def render_with_davinci(
    timeline: dict[str, Any],
    output_video: Path,
    slug: str,
    log: LogFn,
) -> tuple[Path, dict[str, Any]]:
    resolve_api = discover_resolve_api()
    if not resolve_api:
        raise AgentError("未发现 DaVinci Resolve 脚本接口。")
    module_dir, script_lib, install_dir = resolve_api
    script_path = ROOT / "workspace" / "cache" / f"render_{slug}_resolve.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path = ROOT / "workspace" / "cache" / f"render_{slug}_timeline.json"
    write_json(payload_path, timeline)
    report_path = ROOT / "workspace" / "cache" / f"render_{slug}_resolve_report.json"

    script_path.write_text(
        build_resolve_script(payload_path, output_video, slug, report_path),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["RESOLVE_SCRIPT_API"] = str(module_dir.parent)
    env["RESOLVE_SCRIPT_LIB"] = str(script_lib)
    env["PYTHONPATH"] = str(module_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = f"{install_dir};{env.get('PATH', '')}"
    log("正在使用 DaVinci Resolve 创建时间线并导出...")
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
    )
    (ROOT / "outputs" / "logs" / f"{slug}_resolve_stdout.log").write_text(
        completed.stdout + "\n" + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AgentError(completed.stderr.strip() or completed.stdout.strip() or "DaVinci 渲染失败。")
    if not output_video.exists():
        raise AgentError("DaVinci 渲染结束，但没有找到输出文件。")
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return output_video, report


def build_resolve_script(payload_path: Path, output_video: Path, slug: str, report_path: Path) -> str:
    return f'''# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from pathlib import Path

import DaVinciResolveScript as d


TIMELINE_PATH = Path(r"{payload_path}")
OUTPUT_VIDEO = Path(r"{output_video}")
REPORT_PATH = Path(r"{report_path}")
PROJECT_NAME = "AI_Video_Agent"
TIMELINE_NAME = "{slug}"


def frames(seconds, fps):
    return int(round(float(seconds) * float(fps)))


def collect(folder):
    clips = list(folder.GetClipList() or [])
    for subfolder in folder.GetSubFolderList() or []:
        clips.extend(collect(subfolder))
    return clips


def unique_name(project, base):
    names = {{project.GetTimelineByIndex(i).GetName() for i in range(1, project.GetTimelineCount() + 1)}}
    if base not in names:
        return base
    index = 2
    while f"{{base}}_{{index}}" in names:
        index += 1
    return f"{{base}}_{{index}}"


timeline_data = json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))
preset = timeline_data["preset"]
fps = float(preset.get("fps", 30))
resolve = d.scriptapp("Resolve")
if not resolve:
    raise RuntimeError("Cannot connect to Resolve.")
pm = resolve.GetProjectManager()
project = pm.GetCurrentProject()
if not project or project.GetName() != PROJECT_NAME:
    project = pm.LoadProject(PROJECT_NAME) or pm.CreateProject(PROJECT_NAME)
if not project:
    raise RuntimeError("Cannot create or load Resolve project.")

project.SetSetting("timelineFrameRate", str(int(fps) if fps.is_integer() else fps))
try:
    fps = float(project.GetSetting("timelineFrameRate") or fps)
except Exception:
    pass
media_pool = project.GetMediaPool()
timeline_name = unique_name(project, TIMELINE_NAME)
timeline = media_pool.CreateEmptyTimeline(timeline_name)
if not timeline:
    raise RuntimeError("Cannot create timeline.")
project.SetCurrentTimeline(timeline)
timeline.SetSetting("useCustomSettings", "1")
timeline.SetSetting("timelineResolutionWidth", str(preset["width"]))
timeline.SetSetting("timelineResolutionHeight", str(preset["height"]))
try:
    timeline.SetStartTimecode("00:00:00:00")
except Exception:
    pass

source_paths = sorted({{scene["asset"] for scene in timeline_data["scenes"]}})
imported = {{}}
for source in source_paths:
    found = None
    for clip in collect(media_pool.GetRootFolder()):
        props = clip.GetClipProperty() or {{}}
        if (props.get("File Path") or "").lower() == source.lower():
            found = clip
            break
    if not found:
        items = media_pool.ImportMedia([source]) or []
        if items:
            found = items[0]
    if not found:
        raise RuntimeError(f"Resolve could not import {{source}}")
    imported[source] = found

record = 0
failures = []
for scene in timeline_data["scenes"]:
    media_item = imported[scene["asset"]]
    source_fps = fps
    try:
        props = media_item.GetClipProperty() or {{}}
        source_fps = float(props.get("FPS") or fps)
    except Exception:
        pass
    duration_frames = max(1, frames(scene.get("duration", 3), fps))
    request = {{
        "mediaPoolItem": media_item,
        "startFrame": frames(scene.get("start", 0), source_fps),
        "endFrame": frames(float(scene.get("start", 0)) + float(scene.get("duration", 3)), source_fps) - 1,
        "recordFrame": record,
        "trackIndex": 1,
    }}
    items = media_pool.AppendToTimeline([request]) or []
    if not items:
        failures.append(scene["id"])
    else:
        for item in items:
            try:
                item.SetProperty("Scaling", 3)
            except Exception:
                pass
        timeline.AddMarker(record, "Blue", scene.get("caption", scene["id"]), scene.get("notes", ""), duration_frames, f"agent:{{scene['id']}}")
    record += duration_frames

music = timeline_data.get("background_music")
if music and Path(music).exists():
    items = media_pool.ImportMedia([music]) or []
    if items:
        media_pool.AppendToTimeline([{{"mediaPoolItem": items[0], "startFrame": 0, "endFrame": max(1, record - 1), "recordFrame": 0, "trackIndex": 2, "mediaType": 2}}])

pm.SaveProject()
OUTPUT_VIDEO.parent.mkdir(parents=True, exist_ok=True)
try:
    project.DeleteAllRenderJobs()
except Exception:
    pass
format_ok = project.SetCurrentRenderFormatAndCodec("mp4", "H264")
settings_ok = project.SetRenderSettings({{
    "SelectAllFrames": True,
    "TargetDir": str(OUTPUT_VIDEO.parent),
    "CustomName": OUTPUT_VIDEO.stem,
    "ExportVideo": True,
    "ExportAudio": True,
    "FormatWidth": int(preset["width"]),
    "FormatHeight": int(preset["height"]),
    "FrameRate": fps,
    "VideoQuality": "High",
}})
job_id = project.AddRenderJob()
start_ok = False
statuses = []
if job_id:
    start_ok = project.StartRendering(job_id, isInteractiveMode=False)
    started = time.time()
    while project.IsRenderingInProgress() and time.time() - started < 360:
        statuses.append(project.GetRenderJobStatus(job_id))
        time.sleep(2)
    statuses.append(project.GetRenderJobStatus(job_id))

report = {{
    "project": project.GetName(),
    "timeline": timeline.GetName(),
    "format_ok": format_ok,
    "settings_ok": settings_ok,
    "job_id": job_id,
    "start_ok": start_ok,
    "statuses": statuses,
    "failures": failures,
    "output": str(OUTPUT_VIDEO),
}}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
if failures:
    raise RuntimeError("Some scenes failed: " + ", ".join(failures))
if not OUTPUT_VIDEO.exists():
    raise RuntimeError("Render completed without output file.")
print(json.dumps(report, ensure_ascii=False, indent=2))
'''


def discover_resolve_api() -> tuple[Path, Path, Path] | None:
    module_candidates = [
        Path(os.environ.get("RESOLVE_SCRIPT_API", "")) / "Modules",
        Path(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"),
    ]
    install_candidates = [
        Path(os.environ.get("RESOLVE_INSTALL_DIR", "")),
        Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve"),
        Path(r"E:\davinci"),
    ]
    module_dir = next((path for path in module_candidates if (path / "DaVinciResolveScript.py").exists()), None)
    install_dir = next((path for path in install_candidates if path and (path / "fusionscript.dll").exists()), None)
    if not module_dir or not install_dir:
        return None
    return module_dir, install_dir / "fusionscript.dll", install_dir


def dimensions_for_aspect(aspect_ratio: str) -> tuple[int, int]:
    value = aspect_ratio.strip()
    if value in {"横屏 16:9", "16:9", "lecture"}:
        return 1920, 1080
    if value in {"方形 1:1", "1:1"}:
        return 1080, 1080
    return 1080, 1920


def render_srt(scenes: list[dict[str, Any]]) -> str:
    cursor = 0.0
    blocks = []
    for index, scene in enumerate(scenes, start=1):
        duration = float(scene.get("duration", 3.0))
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
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def sample_timestamps(duration: float) -> list[float]:
    if duration <= 0:
        return [0.2]
    if duration <= 6:
        return [max(0.1, duration * 0.25), max(0.2, duration * 0.65)]
    return [0.5, duration * 0.35, duration * 0.7, max(0.5, duration - 0.8)]


def media_duration(item: dict[str, Any]) -> float:
    try:
        return float(item.get("probe", {}).get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


def media_resolution(item: dict[str, Any]) -> str:
    for stream in item.get("probe", {}).get("streams", []):
        if stream.get("codec_type") == "video":
            width = stream.get("width")
            height = stream.get("height")
            if width and height:
                return f"{width}x{height}"
    return ""


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_slug(value: str) -> str:
    allowed = []
    for char in value.strip():
        if char.isalnum() or char in {"-", "_"}:
            allowed.append(char)
        elif char.isspace():
            allowed.append("_")
    slug = "".join(allowed).strip("_")
    return slug or "ai_edit"


def find_ffmpeg() -> str | None:
    local_ffmpeg = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
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


def find_ffprobe() -> str | None:
    local_ffprobe = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
    if local_ffprobe.exists():
        return str(local_ffprobe)
    return shutil.which("ffprobe")


def run_command(cmd: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n\n$ " + " ".join(cmd) + "\n")
        completed = subprocess.run(cmd, stdout=log, stderr=log, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise AgentError(f"命令执行失败，查看日志：{log_path}")
