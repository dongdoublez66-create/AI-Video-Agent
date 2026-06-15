from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 120


class LLMError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @property
    def chat_completions_url(self) -> str:
        base_url = self.config.base_url.strip().rstrip("/")
        if not base_url:
            raise LLMError("请填写 Base URL。")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def validate(self) -> str:
        payload = {
            "model": self.config.model.strip(),
            "messages": [{"role": "user", "content": "请只回复 OK。"}],
            "temperature": 0,
            "max_tokens": 16,
        }
        content = self.chat(payload)
        if not content.strip():
            raise LLMError("接口返回为空。")
        return content.strip()

    def complete_json(self, messages: list[dict[str, Any]], temperature: float = 0.35) -> dict[str, Any]:
        payload = {
            "model": self.config.model.strip(),
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        content = self.chat(payload)
        return parse_json_object(content)

    def chat(self, payload: dict[str, Any]) -> str:
        if not self.config.api_key.strip():
            raise LLMError("请填写 API Key。")
        if not self.config.model.strip():
            raise LLMError("请填写模型名称。")

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.chat_completions_url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key.strip()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"API 请求失败：HTTP {exc.code}\n{detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"无法连接 API：{exc.reason}") from exc

        try:
            payload = json.loads(body)
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError(f"API 返回格式无法解析：{body[:500]}") from exc


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first == -1 or last == -1 or last <= first:
        raise LLMError(f"模型没有返回 JSON 对象：{text[:500]}")
    try:
        value = json.loads(cleaned[first : last + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型返回的 JSON 无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("模型返回的 JSON 顶层不是对象。")
    return value
