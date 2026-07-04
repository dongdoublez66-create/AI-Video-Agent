from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STYLE_PRIORITY_TERMS_CN = (
    "画面构成",
    "分割",
    "肌理",
    "色调",
    "黑白灰关系",
    "表现画法",
    "抽象画法",
    "点线面构成",
    "块面关系",
    "色彩关系",
    "统一色调",
    "同类色对比",
    "类似色对比",
    "互补色对比",
)

STYLE_PRIORITY_GUIDE_CN = (
    "以下是最高优先级的风格分析维度，请把它们放在媒介、题材和故事描述之前："
    "画面构成、分割、肌理、色调、黑白灰关系、表现画法、抽象画法、点线面构成、"
    "块面关系、色彩关系、统一色调、同类色对比、类似色对比、互补色对比。"
)

STYLE_PRIORITY_PROMPT_EN = (
    "high-priority art-direction constraints: image composition, visual segmentation, "
    "surface texture and material grain, tonal palette, black-white-gray value structure, "
    "expressive painting method, abstract painting treatment, point-line-plane composition, "
    "block and plane relationships, color relationships, unified tonal harmony, "
    "same-hue contrast, analogous color contrast, complementary color contrast"
)


STYLE_ANALYSIS_PROMPT = (
    "请详细描述这幅画的视觉风格，用于 Stable Diffusion / SDXL 提示词生成。"
    f"{STYLE_PRIORITY_GUIDE_CN}"
    "请按这些维度优先分析："
    "1）画面构成与分割：主体位置、空间切分、视线流动、留白、疏密节奏；"
    "2）肌理与画法：笔触、印刷感、纸张感、颗粒、刮擦、表现画法或抽象画法；"
    "3）黑白灰关系：明度层级、暗部/中间调/亮部比例、整体压暗或提亮方式；"
    "4）点线面构成与块面关系：线条方向、几何块面、形体概括、平面化程度；"
    "5）色彩关系：统一色调、同类色对比、类似色对比、互补色对比、饱和度和冷暖关系。"
    "再补充媒介类型、流派、人物造型、空间关系、纹理、纸张或印刷质感。"
    "不要复述画面故事，也不要生成新内容。最后给出一段可直接用于图像生成的中文风格提示词。"
)


PROMPT_REWRITE_SYSTEM = (
    "你是图像生成提示词工程师。请把用户的中文需求改写为适合 SDXL 的英文 positive prompt 和 negative prompt。"
    "如果给了风格分析，要把风格转成清晰的视觉约束，但不要改变用户要求的主体内容。"
    f"必须把这些维度作为最高权重写入 positive prompt 的前半部分：{STYLE_PRIORITY_PROMPT_EN}。"
    "当任务是参考图风格迁移或保留内容改风格时，优先迁移这些风格维度，而不是替换原图主体。"
    "只返回 JSON，格式为 {\"pos\": \"...\", \"neg\": \"...\"}。"
)


@dataclass(frozen=True)
class PromptPair:
    positive: str
    negative: str


class LLMService:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key.strip() or os.environ.get("DASHSCOPE_API_KEY", "").strip()
        self.enabled = bool(self.api_key)
        self.vision_model = "qwen-vl-max"
        self.text_model = "qwen-plus"
        self.text_fallback_model = "qwen-turbo"

    def analyze_style(self, image_path: Path) -> str:
        if not self.enabled:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY。")
        dashscope = self._dashscope()
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": self._image_uri(image_path)},
                    {"text": STYLE_ANALYSIS_PROMPT},
                ],
            }
        ]
        response = dashscope.MultiModalConversation.call(model=self.vision_model, messages=messages)
        self._raise_for_dashscope_error(response)
        text = extract_dashscope_text(response)
        if not text:
            raise RuntimeError("Qwen-VL 没有返回可用的风格分析文本。")
        return text.strip()

    def text2prompt(self, user_text: str, style_description: str = "") -> tuple[str, str]:
        if not self.enabled:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY。")
        prompt = (
            f"{PROMPT_REWRITE_SYSTEM}\n\n"
            f"用户需求：{user_text.strip()}\n\n"
            f"风格分析：{style_description.strip() or '无'}\n"
            "要求：positive prompt 必须是英文，并且先写高权重美术风格约束，再写主体内容。"
            "请重点保留/迁移画面构成、分割、肌理、色调、黑白灰关系、表现画法、抽象画法、"
            "点线面构成、块面关系、色彩关系、统一色调、同类色对比、类似色对比、互补色对比；"
            "negative prompt 用英文列出低质量、变形、多余文字、水印、主体错乱等问题。"
        )
        last_error: Exception | None = None
        for model in (self.text_model, self.text_fallback_model):
            try:
                response = self._dashscope().Generation.call(model=model, prompt=prompt)
                self._raise_for_dashscope_error(response)
                text = extract_dashscope_text(response)
                pair = parse_prompt_pair(text)
                return pair.positive, pair.negative
            except Exception as exc:  # noqa: BLE001 - try fallback model.
                last_error = exc
        raise RuntimeError(f"提示词生成失败：{last_error}")

    def chat_adjust(self, history: list[dict[str, str]], new_request: str) -> str:
        content = "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history[-6:])
        positive, _negative = self.text2prompt(f"{content}\n新的调整要求：{new_request}")
        return positive

    def _dashscope(self) -> Any:
        try:
            import dashscope
        except ImportError as exc:
            raise RuntimeError("缺少 dashscope 依赖，请先运行 pip install dashscope。") from exc
        dashscope.api_key = self.api_key
        return dashscope

    def _image_uri(self, path: Path) -> str:
        return path.expanduser().resolve().as_uri()

    def _raise_for_dashscope_error(self, response: Any) -> None:
        status_code = getattr(response, "status_code", None)
        if status_code is None and isinstance(response, dict):
            status_code = response.get("status_code")
        if status_code and int(status_code) >= 400:
            message = getattr(response, "message", None)
            if message is None and isinstance(response, dict):
                message = response.get("message") or response.get("code")
            raise RuntimeError(f"DashScope 请求失败：{message or status_code}")


def extract_dashscope_text(response: Any) -> str:
    if isinstance(response, dict):
        return extract_text_from_obj(response)
    output = getattr(response, "output", None)
    if output is not None:
        text = extract_text_from_obj(output)
        if text:
            return text
    return extract_text_from_obj(response)


def extract_text_from_obj(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        candidates = [
            value.get("text"),
            value.get("content"),
            value.get("response"),
            value.get("result"),
        ]
        output = value.get("output")
        if output is not None:
            candidates.append(output)
        choices = value.get("choices")
        if choices is not None:
            candidates.append(choices)
        for item in candidates:
            text = extract_text_from_obj(item)
            if text:
                return text
    if isinstance(value, list):
        parts = [extract_text_from_obj(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    for attr in ("text", "content", "message", "choices"):
        if hasattr(value, attr):
            text = extract_text_from_obj(getattr(value, attr))
            if text:
                return text
    return ""


def parse_prompt_pair(text: str) -> PromptPair:
    payload = parse_json_object(text)
    positive = str(payload.get("pos") or payload.get("positive") or "").strip()
    negative = str(payload.get("neg") or payload.get("negative") or "").strip()
    if not positive:
        raise RuntimeError(f"提示词 JSON 缺少 pos 字段：{text[:300]}")
    return PromptPair(positive=positive, negative=negative)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise RuntimeError("提示词返回值不是 JSON 对象。")
    return value
