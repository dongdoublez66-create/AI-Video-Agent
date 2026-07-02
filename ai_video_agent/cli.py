from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import discover_resolve_api, find_ffmpeg, find_ffprobe
from .config import PROJECT_DIRS, ROOT
from .image_agent import ImageRequest, run_image_generation


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-video-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="检查本地剪辑依赖。")
    subparsers.add_parser("init", help="创建标准工作目录。")
    subparsers.add_parser("gui", help="打开 Windows 桌面 Agent。")

    image_parser = subparsers.add_parser("image", help="通过命令行生成图片。")
    image_parser.add_argument("--prompt", required=True, help="图片提示词。")
    image_parser.add_argument("--mode", default="text_to_image", choices=["text_to_image", "style_reference", "edit_style"])
    image_parser.add_argument("--dashscope-api-key", default=os.environ.get("DASHSCOPE_API_KEY", ""))
    image_parser.add_argument("--model", default="", help="SDXL 基础模型 ID 或本地模型路径。留空使用默认 SDXL base。")
    image_parser.add_argument("--reference-image")
    image_parser.add_argument("--style-reference-image")
    image_parser.add_argument("--content-image")
    image_parser.add_argument("--style-description", default="", help="可选：手动填写或预先分析好的风格描述。")
    image_parser.add_argument("--negative-prompt", default="", help="可选：负面提示词。")
    image_parser.add_argument("--out-dir", default=str(ROOT / "outputs" / "images"))
    image_parser.add_argument("--name", default="ai_image")
    image_parser.add_argument("--size", default="1024x1024")
    image_parser.add_argument("--count", type=int, default=1)
    image_parser.add_argument("--steps", type=int, default=25)
    image_parser.add_argument("--seed", type=int, default=42)
    image_parser.add_argument("--content-strength", type=float, default=0.62)
    image_parser.add_argument("--style-strength", type=float, default=0.60)
    image_parser.add_argument("--no-smart-prompt", action="store_true", help="关闭 DashScope 智能提示词改写。")

    args = parser.parse_args()

    if args.command == "doctor":
        doctor()
    elif args.command == "init":
        init_workspace()
    elif args.command == "gui":
        from .gui import main as gui_main

        gui_main()
    elif args.command == "image":
        generate_image(args)


def init_workspace() -> None:
    for folder in PROJECT_DIRS:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    print(f"工作目录已就绪：{ROOT}")


def doctor() -> None:
    init_workspace()
    resolve_api = discover_resolve_api()
    checks = {
        "python": sys.executable,
        "ffmpeg": find_ffmpeg(),
        "ffprobe": find_ffprobe(),
        "ffmpeg_probe_fallback": bool(find_ffmpeg()),
        "davinci_resolve_api": {
            "available": bool(resolve_api),
            "module_dir": str(resolve_api[0]) if resolve_api else "",
            "script_lib": str(resolve_api[1]) if resolve_api else "",
            "install_dir": str(resolve_api[2]) if resolve_api else "",
        },
    }
    print(json.dumps(checks, indent=2, ensure_ascii=False))
    if not checks["ffmpeg"]:
        print("\n没有找到 FFmpeg。可以安装到系统 PATH，或放到 tools/ffmpeg/bin/ffmpeg.exe。")


def generate_image(args: argparse.Namespace) -> None:
    request = ImageRequest(
        mode=args.mode,
        backend="local_sdxl",
        prompt=args.prompt,
        output_dir=Path(args.out_dir),
        output_name=args.name,
        api_key=args.dashscope_api_key,
        model=args.model,
        negative_prompt=args.negative_prompt,
        reference_image=Path(args.reference_image) if args.reference_image else None,
        style_reference_image=Path(args.style_reference_image) if args.style_reference_image else None,
        content_image=Path(args.content_image) if args.content_image else None,
        style_description=args.style_description,
        size=args.size,
        count=args.count,
        steps=args.steps,
        seed=args.seed,
        content_strength=args.content_strength,
        style_strength=args.style_strength,
        smart_prompt=not args.no_smart_prompt,
    )
    result = run_image_generation(request)
    print("图片生成完成：")
    for image in result.images:
        print(f"  {image}")
    print(f"报告：{result.report_path}")
