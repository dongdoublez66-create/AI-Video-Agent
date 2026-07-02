from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import (
    BASE_IMAGE_MODEL_ID,
    CONTROLNET_CANNY_HIGH,
    CONTROLNET_CANNY_LOW,
    CONTROLNET_MODEL_ID,
    DEFAULT_GUIDANCE_SCALE,
    DEFAULT_IMAGE_STEPS,
    DEFAULT_IP_ADAPTER_SCALE,
    DEFAULT_NEGATIVE_PROMPT,
    IP_ADAPTER_MODEL_ID,
    IP_ADAPTER_SUBFOLDER,
    IP_ADAPTER_WEIGHT_NAME,
    ROOT,
)
from .image_llm import LLMService


os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class ImageRequest:
    mode: str
    prompt: str
    output_dir: Path
    output_name: str
    backend: str = "local_sdxl"
    model: str = ""
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    reference_image: Path | None = None
    style_reference_image: Path | None = None
    content_image: Path | None = None
    style_description: str = ""
    size: str = "1024x1024"
    count: int = 1
    steps: int = DEFAULT_IMAGE_STEPS
    seed: int = 42
    guidance_scale: float = DEFAULT_GUIDANCE_SCALE
    content_strength: float = 0.62
    style_strength: float = DEFAULT_IP_ADAPTER_SCALE
    canny_low: int = CONTROLNET_CANNY_LOW
    canny_high: int = CONTROLNET_CANNY_HIGH
    api_key: str = ""
    smart_prompt: bool = True
    # Kept for compatibility with older GUI/CLI call sites. They are no longer
    # used by the local SDXL image engine.
    base_url: str = ""
    quality: str = ""


@dataclass(frozen=True)
class ImageResult:
    backend: str
    mode: str
    images: list[Path]
    report_path: Path
    raw_response_path: Path | None = None


class ImageGenerationError(RuntimeError):
    pass


def run_image_generation(request: ImageRequest, log: LogFn = print) -> ImageResult:
    if request.backend not in {"", "local_sdxl", "diffusers"}:
        raise ImageGenerationError(
            "图片生成已经重构为本地 SDXL 引擎，不再使用旧版图片后端。"
        )
    if not request.prompt.strip():
        raise ImageGenerationError("请填写图片提示词。")

    style_reference = request.style_reference_image or request.reference_image
    if request.mode == "style_reference":
        if not style_reference or not style_reference.exists():
            raise ImageGenerationError("参考图风格迁移需要选择一张风格参考图。")
        if not request.content_image or not request.content_image.exists():
            raise ImageGenerationError("参考图风格迁移需要选择一张内容图片。")
    if request.mode == "edit_style" and (not request.content_image or not request.content_image.exists()):
        raise ImageGenerationError("保留内容改风格需要选择一张内容图片。")

    output_dir = request.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = safe_slug(request.output_name or f"image_{datetime.now():%Y%m%d_%H%M%S}")
    report_dir = ROOT / "workspace" / "runs" / f"{datetime.now():%Y%m%d_%H%M%S}_{slug}_image"
    report_dir.mkdir(parents=True, exist_ok=True)

    log("图片生成：使用本地 SDXL + IP-Adapter + ControlNet 引擎")
    prompt_plan = build_prompt_plan(request, style_reference, report_dir, log)
    prompt_path = report_dir / "prompt_plan.json"
    prompt_path.write_text(json.dumps(prompt_plan, ensure_ascii=False, indent=2), encoding="utf-8")

    generator = ImageGenerator(model_id=request.model.strip() or BASE_IMAGE_MODEL_ID, log=log)
    if request.mode == "text_to_image":
        images = generator.txt2img(
            prompt=prompt_plan["positive_prompt"],
            negative_prompt=prompt_plan["negative_prompt"],
            style_reference_image=style_reference,
            request=request,
        )
    elif request.mode == "style_reference":
        images = generator.restyle_with_reference(
            content_image=request.content_image,
            style_reference_image=style_reference,
            prompt=prompt_plan["positive_prompt"],
            negative_prompt=prompt_plan["negative_prompt"],
            request=request,
        )
    elif request.mode == "edit_style":
        images = generator.restyle_with_text(
            content_image=request.content_image,
            prompt=prompt_plan["positive_prompt"],
            negative_prompt=prompt_plan["negative_prompt"],
            request=request,
        )
    else:
        raise ImageGenerationError(f"未知图片生成模式：{request.mode}")

    saved = save_images(images, output_dir, slug, log)
    report_path = report_dir / "image_report.json"
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "backend": "local_sdxl",
        "mode": request.mode,
        "model": request.model.strip() or BASE_IMAGE_MODEL_ID,
        "prompt": request.prompt,
        "positive_prompt": prompt_plan["positive_prompt"],
        "negative_prompt": prompt_plan["negative_prompt"],
        "style_description": prompt_plan.get("style_description", ""),
        "style_reference_image": str(style_reference) if style_reference else "",
        "content_image": str(request.content_image) if request.content_image else "",
        "size": request.size,
        "count": request.count,
        "steps": request.steps,
        "seed": request.seed,
        "guidance_scale": request.guidance_scale,
        "content_strength": request.content_strength,
        "style_strength": request.style_strength,
        "canny_low": request.canny_low,
        "canny_high": request.canny_high,
        "images": [str(path) for path in saved],
        "prompt_plan": str(prompt_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return ImageResult("local_sdxl", request.mode, saved, report_path, prompt_path)


def build_prompt_plan(
    request: ImageRequest,
    style_reference: Path | None,
    report_dir: Path,
    log: LogFn,
) -> dict[str, str]:
    style_description = request.style_description.strip()
    llm = LLMService(api_key=request.api_key.strip())

    if request.smart_prompt and style_reference and not style_description:
        if llm.enabled:
            try:
                log("正在用 Qwen-VL 分析风格参考图...")
                style_description = llm.analyze_style(style_reference)
                (report_dir / "style_analysis.txt").write_text(style_description, encoding="utf-8")
                log("风格参考图分析完成。")
            except Exception as exc:  # noqa: BLE001 - local generation can continue without LLM.
                log(f"风格图分析失败，将直接使用本地风格注入：{exc}")
        else:
            log("未配置 DashScope API Key，跳过智能风格分析；本地 IP-Adapter 仍会使用参考图。")

    if request.smart_prompt and llm.enabled:
        try:
            positive, negative = llm.text2prompt(request.prompt.strip(), style_description)
            if positive.strip():
                return {
                    "positive_prompt": positive.strip(),
                    "negative_prompt": negative.strip() or request.negative_prompt,
                    "style_description": style_description,
                }
        except Exception as exc:  # noqa: BLE001 - fall back to deterministic prompt builder.
            log(f"智能提示词生成失败，将使用内置提示词模板：{exc}")

    return {
        "positive_prompt": build_fallback_positive_prompt(request, style_description),
        "negative_prompt": request.negative_prompt.strip() or DEFAULT_NEGATIVE_PROMPT,
        "style_description": style_description,
    }


def build_fallback_positive_prompt(request: ImageRequest, style_description: str) -> str:
    user_prompt = request.prompt.strip()
    parts = [user_prompt]
    if request.mode == "text_to_image":
        parts.append("high quality SDXL image, coherent composition, rich details")
    elif request.mode == "style_reference":
        parts.append(
            "preserve the content image composition, silhouettes, subject placement and spatial relationships"
        )
    elif request.mode == "edit_style":
        parts.append("preserve the source image structure and edges, change only the visual style")
    if style_description:
        parts.append(f"style reference analysis: {style_description}")
    parts.append(
        "artwork style, painterly rendering, visible brushwork or print texture, refined color palette, no text watermark"
    )
    return ", ".join(part for part in parts if part)


class ImageGenerator:
    def __init__(self, model_id: str, log: LogFn = print) -> None:
        self.model_id = model_id
        self.log = log
        self._torch = None
        self._base_pipe = None
        self._control_pipe = None
        self._base_ip_adapter_loaded = False
        self._control_ip_adapter_loaded = False

    def txt2img(
        self,
        prompt: str,
        negative_prompt: str,
        style_reference_image: Path | None,
        request: ImageRequest,
    ) -> list[Any]:
        pipe = self._load_base_pipe()
        width, height = parse_image_size(request.size)
        kwargs = self._common_kwargs(prompt, negative_prompt, request)
        kwargs.update({"width": width, "height": height})
        if style_reference_image and style_reference_image.exists():
            self._ensure_ip_adapter(pipe, target="base")
            pipe.set_ip_adapter_scale(clamp_float(request.style_strength, 0.0, 1.5))
            kwargs["ip_adapter_image"] = self._open_image(style_reference_image, width, height)
        return self._run_pipe(pipe, kwargs, request, "文生图")

    def restyle_with_text(
        self,
        content_image: Path | None,
        prompt: str,
        negative_prompt: str,
        request: ImageRequest,
    ) -> list[Any]:
        if not content_image:
            raise ImageGenerationError("缺少内容图片。")
        pipe = self._load_control_pipe(load_ip_adapter=False)
        width, height = parse_image_size(request.size)
        source = self._open_image(content_image, width, height)
        canny = self._build_canny_image(source, request.canny_low, request.canny_high)
        kwargs = self._common_kwargs(prompt, negative_prompt, request)
        kwargs.update(
            {
                "image": source,
                "control_image": canny,
                "strength": clamp_float(request.content_strength, 0.05, 0.95),
                "controlnet_conditioning_scale": 0.72,
            }
        )
        return self._run_pipe(pipe, kwargs, request, "保留内容改风格")

    def restyle_with_reference(
        self,
        content_image: Path | None,
        style_reference_image: Path | None,
        prompt: str,
        negative_prompt: str,
        request: ImageRequest,
    ) -> list[Any]:
        if not content_image:
            raise ImageGenerationError("缺少内容图片。")
        if not style_reference_image:
            raise ImageGenerationError("缺少风格参考图。")
        pipe = self._load_control_pipe(load_ip_adapter=True)
        width, height = parse_image_size(request.size)
        source = self._open_image(content_image, width, height)
        style = self._open_image(style_reference_image, width, height)
        canny = self._build_canny_image(source, request.canny_low, request.canny_high)
        pipe.set_ip_adapter_scale(clamp_float(request.style_strength, 0.0, 1.5))
        kwargs = self._common_kwargs(prompt, negative_prompt, request)
        kwargs.update(
            {
                "image": source,
                "control_image": canny,
                "ip_adapter_image": style,
                "strength": clamp_float(request.content_strength, 0.05, 0.95),
                "controlnet_conditioning_scale": 0.78,
            }
        )
        return self._run_pipe(pipe, kwargs, request, "参考图风格迁移")

    def _load_base_pipe(self) -> Any:
        if self._base_pipe is not None:
            return self._base_pipe
        torch = self._import_torch()
        try:
            from diffusers import StableDiffusionXLPipeline
        except ImportError as exc:
            raise missing_dependency_error("diffusers") from exc

        dtype = torch.float16 if self._device() == "cuda" else torch.float32
        ensure_hf_model_snapshot(
            self.model_id,
            sdxl_snapshot_patterns(fp16=self._device() == "cuda"),
            self.log,
        )
        self.log(f"加载 SDXL 基础模型：{self.model_id}")
        pipe_kwargs: dict[str, Any] = {"torch_dtype": dtype, "use_safetensors": True}
        if self._device() == "cuda":
            pipe_kwargs["variant"] = "fp16"
        pipe = StableDiffusionXLPipeline.from_pretrained(self.model_id, **pipe_kwargs)
        self._place_pipe(pipe)
        self._base_pipe = pipe
        return pipe

    def _load_control_pipe(self, load_ip_adapter: bool) -> Any:
        if self._control_pipe is not None:
            if load_ip_adapter:
                self._ensure_ip_adapter(self._control_pipe, target="control")
            return self._control_pipe
        torch = self._import_torch()
        try:
            from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
        except ImportError as exc:
            raise missing_dependency_error("diffusers") from exc

        dtype = torch.float16 if self._device() == "cuda" else torch.float32
        ensure_hf_model_snapshot(
            CONTROLNET_MODEL_ID,
            ["config.json", "diffusion_pytorch_model.safetensors"],
            self.log,
        )
        self.log(f"加载 ControlNet Canny 模型：{CONTROLNET_MODEL_ID}")
        controlnet = ControlNetModel.from_pretrained(CONTROLNET_MODEL_ID, torch_dtype=dtype)
        ensure_hf_model_snapshot(
            self.model_id,
            sdxl_snapshot_patterns(fp16=self._device() == "cuda"),
            self.log,
        )
        self.log(f"加载 SDXL ControlNet 图生图管线：{self.model_id}")
        pipe_kwargs = {"controlnet": controlnet, "torch_dtype": dtype, "use_safetensors": True}
        if self._device() == "cuda":
            pipe_kwargs["variant"] = "fp16"
        pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(self.model_id, **pipe_kwargs)
        self._place_pipe(pipe)
        self._control_pipe = pipe
        if load_ip_adapter:
            self._ensure_ip_adapter(pipe, target="control")
        return pipe

    def _ensure_ip_adapter(self, pipe: Any, target: str) -> None:
        if target == "base" and self._base_ip_adapter_loaded:
            return
        if target == "control" and self._control_ip_adapter_loaded:
            return
        ensure_hf_model_snapshot(
            IP_ADAPTER_MODEL_ID,
            [
                f"{IP_ADAPTER_SUBFOLDER}/{IP_ADAPTER_WEIGHT_NAME}",
                "models/image_encoder/config.json",
                "models/image_encoder/model.safetensors",
            ],
            self.log,
        )
        self.log("加载 IP-Adapter 风格参考权重...")
        pipe.load_ip_adapter(
            IP_ADAPTER_MODEL_ID,
            subfolder=IP_ADAPTER_SUBFOLDER,
            weight_name=IP_ADAPTER_WEIGHT_NAME,
            image_encoder_folder="models/image_encoder",
        )
        # IP-Adapter is attached after the pipeline is created. If the base
        # pipeline has already been offloaded, newly registered adapter modules
        # can otherwise remain on CPU while the denoising inputs are on CUDA,
        # causing "Input type cuda half and weight type CPU half" errors.
        self._place_pipe(pipe)
        if target == "base":
            self._base_ip_adapter_loaded = True
        else:
            self._control_ip_adapter_loaded = True

    def _place_pipe(self, pipe: Any) -> None:
        device = self._device()
        if device == "cuda" and hasattr(pipe, "enable_model_cpu_offload"):
            pipe.enable_model_cpu_offload()
            return
        pipe.to(device)

    def _common_kwargs(self, prompt: str, negative_prompt: str, request: ImageRequest) -> dict[str, Any]:
        return {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "num_inference_steps": max(1, int(request.steps)),
            "guidance_scale": float(request.guidance_scale),
        }

    def _run_pipe(self, pipe: Any, kwargs: dict[str, Any], request: ImageRequest, label: str) -> list[Any]:
        torch = self._import_torch()
        images = []
        count = max(1, min(int(request.count), 4))
        for index in range(count):
            seed = int(request.seed) + index
            self.log(f"{label}：第 {index + 1}/{count} 张，seed={seed}")
            generator = torch.Generator(device=self._device()).manual_seed(seed)
            result = pipe(**kwargs, generator=generator)
            images.append(result.images[0])
        return images

    def _build_canny_image(self, image: Any, low: int, high: int) -> Any:
        try:
            import cv2
            import numpy as np
            from PIL import Image
        except ImportError as exc:
            raise missing_dependency_error("opencv-python / numpy / Pillow") from exc

        array = np.array(image.convert("RGB"))
        edges = cv2.Canny(array, int(low), int(high))
        edges = edges[:, :, None]
        edges = np.concatenate([edges, edges, edges], axis=2)
        return Image.fromarray(edges)

    def _open_image(self, path: Path, width: int, height: int) -> Any:
        try:
            from PIL import Image
        except ImportError as exc:
            raise missing_dependency_error("Pillow") from exc
        image = Image.open(path).convert("RGB")
        return fit_image(image, width, height)

    def _import_torch(self) -> Any:
        if self._torch is not None:
            return self._torch
        try:
            import torch
        except ImportError as exc:
            raise missing_dependency_error("torch") from exc
        self._torch = torch
        return torch

    def _device(self) -> str:
        torch = self._import_torch()
        return "cuda" if torch.cuda.is_available() else "cpu"


def fit_image(image: Any, width: int, height: int) -> Any:
    from PIL import Image

    source_width, source_height = image.size
    scale = max(width / source_width, height / source_height)
    resized = image.resize((round(source_width * scale), round(source_height * scale)), Image.LANCZOS)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def save_images(images: list[Any], output_dir: Path, slug: str, log: LogFn) -> list[Path]:
    saved = []
    for index, image in enumerate(images, start=1):
        target = output_dir / f"{slug}_{index:02d}.png"
        image.save(target)
        saved.append(target)
        log(f"图片已保存：{target}")
    return saved


def parse_image_size(size: str) -> tuple[int, int]:
    if "x" in size:
        left, right = size.lower().split("x", 1)
        try:
            width = round_to_multiple(max(256, int(left)), 8)
            height = round_to_multiple(max(256, int(right)), 8)
            return width, height
        except ValueError:
            pass
    return 1024, 1024


def round_to_multiple(value: int, factor: int) -> int:
    return max(factor, value - value % factor)


def clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def missing_dependency_error(package: str) -> ImageGenerationError:
    return ImageGenerationError(
        f"缺少本地图片生成依赖：{package}。请先按 README 安装 PyTorch CUDA 版和 requirements.txt。"
    )


def ensure_hf_model_snapshot(repo_id_or_path: str, allow_patterns: list[str], log: LogFn) -> None:
    if Path(repo_id_or_path).expanduser().exists():
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise missing_dependency_error("huggingface_hub") from exc

    endpoint = os.environ.get("HF_ENDPOINT", "").strip() or None
    endpoint_note = f"，endpoint={endpoint}" if endpoint else ""
    log(f"首次使用需要下载/检查模型：{repo_id_or_path}{endpoint_note}")
    log("如果这里长时间不动，一般是 Hugging Face 连接慢；可以设置 HF_ENDPOINT=https://hf-mirror.com 后重试。")
    try:
        dry_run_items = snapshot_download(
            repo_id_or_path,
            allow_patterns=allow_patterns,
            etag_timeout=30,
            max_workers=2,
            endpoint=endpoint,
            dry_run=True,
        )
        total = sum((getattr(item, "file_size", 0) or 0) for item in dry_run_items if getattr(item, "will_download", True))
        if total > 0:
            log(f"预计还需下载约 {total / 1024 / 1024 / 1024:.2f} GB：{repo_id_or_path}")
    except Exception as exc:  # noqa: BLE001 - dry run is only for better logging.
        log(f"模型下载量预估失败，继续尝试下载：{exc}")

    stop_heartbeat = threading.Event()

    def heartbeat() -> None:
        while not stop_heartbeat.wait(30):
            log(f"仍在下载/检查模型：{repo_id_or_path}，请保持网络连接...")

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        snapshot_download(
            repo_id_or_path,
            allow_patterns=allow_patterns,
            etag_timeout=30,
            max_workers=2,
            endpoint=endpoint,
        )
    except Exception as exc:
        raise ImageGenerationError(
            f"模型下载失败：{repo_id_or_path}\n"
            f"原因：{exc}\n"
            "可尝试在 PowerShell 设置镜像后重启：$env:HF_ENDPOINT='https://hf-mirror.com'"
        ) from exc
    finally:
        stop_heartbeat.set()
    log(f"模型检查完成：{repo_id_or_path}")


def sdxl_snapshot_patterns(fp16: bool) -> list[str]:
    weight_suffix = ".fp16.safetensors" if fp16 else ".safetensors"
    return [
        "model_index.json",
        "scheduler/scheduler_config.json",
        "tokenizer/merges.txt",
        "tokenizer/special_tokens_map.json",
        "tokenizer/tokenizer_config.json",
        "tokenizer/vocab.json",
        "tokenizer_2/merges.txt",
        "tokenizer_2/special_tokens_map.json",
        "tokenizer_2/tokenizer_config.json",
        "tokenizer_2/vocab.json",
        "text_encoder/config.json",
        f"text_encoder/model{weight_suffix}",
        "text_encoder_2/config.json",
        f"text_encoder_2/model{weight_suffix}",
        "unet/config.json",
        f"unet/diffusion_pytorch_model{weight_suffix}",
        "vae/config.json",
        f"vae/diffusion_pytorch_model{weight_suffix}",
    ]


def safe_slug(value: str) -> str:
    allowed = []
    for char in value.strip():
        if char.isalnum() or char in {"-", "_"}:
            allowed.append(char)
        elif char.isspace():
            allowed.append("_")
    return "".join(allowed).strip("_") or "image"


def env_dashscope_key() -> str:
    return os.environ.get("DASHSCOPE_API_KEY", "").strip()
