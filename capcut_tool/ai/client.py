"""Gọi model AI để lập kế hoạch biến thể mẫu.

Hỗ trợ cả model trả phí và miễn phí:

- Claude (Anthropic) — dùng ``ANTHROPIC_API_KEY`` hoặc key lưu trong app.
- OpenAI, OpenRouter, Groq, Google Gemini — qua chuẩn OpenAI-compatible.
  OpenRouter có nhiều model ``:free``, Groq và Gemini có hạn mức miễn phí.
- Ollama — chạy local, miễn phí, không cần mạng.

Không cấu hình được model nào thì phần gọi tự chuyển sang phương án dự phòng
offline (quy tắc + câu mẫu), app vẫn chạy bình thường.

Lưu ý: Veo 3 là model tạo video, không viết được kế hoạch cho project CapCut.
Muốn dùng Veo 3 thì tạo clip riêng rồi đưa clip vào CapCut như nguyên liệu.
"""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlparse


class AIUnavailable(RuntimeError):
    """Chưa cấu hình model, hoặc model trả lỗi không dùng được."""


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


# provider -> thông tin mặc định. Model free có thể đổi tên theo thời điểm,
# bạn sửa ô Model trong hộp thoại Cấu hình AI nếu nhà cung cấp đổi tên.
PROVIDERS: dict[str, dict[str, str]] = {
    "anthropic": {
        "label": "Claude (Anthropic)",
        "model": os.environ.get("CAPTION_MODEL", "claude-opus-5-5"),
        "base_url": "https://api.anthropic.com",
        "key_help": "ANTHROPIC_API_KEY",
    },
    "openrouter": {
        "label": "OpenRouter (có model free)",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "base_url": "https://openrouter.ai/api/v1",
        "key_help": "OPENROUTER_API_KEY",
    },
    "groq": {
        "label": "Groq (hạn mức miễn phí)",
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "key_help": "GROQ_API_KEY",
    },
    "gemini": {
        "label": "Google Gemini (hạn mức miễn phí)",
        "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_help": "GEMINI_API_KEY",
    },
    "openai": {
        "label": "OpenAI",
        "model": "gpt-4.1-mini",
        "base_url": "https://api.openai.com/v1",
        "key_help": "OPENAI_API_KEY",
    },
    "ollama": {
        "label": "Ollama (local, miễn phí)",
        "model": "llama3.1",
        "base_url": "http://localhost:11434",
        "key_help": "",
    },
    "custom": {
        "label": "OpenAI-compatible tự nhập",
        "model": "",
        "base_url": "",
        "key_help": "",
    },
}

ENV_KEYS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

# Gợi ý model cho hộp thoại. Ô chọn vẫn cho phép gõ tay vì tên model free
# thay đổi thường xuyên; danh sách này chỉ để chọn nhanh.
MODEL_CHOICES: dict[str, list[str]] = {
    "anthropic": ["claude-opus-5-5", "claude-sonnet-4-5", "claude-3-7-sonnet-latest"],
    "openrouter": [
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-r1:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "google/gemma-3-27b-it:free",
    ],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
    "ollama": ["llama3.1", "qwen2.5", "mistral", "gemma3"],
    "custom": [],
}

# Thứ tự tự dò khi chọn "Tự động": model đang có sẵn key sẽ được dùng trước.
PROVIDER_ORDER = ("anthropic", "openrouter", "groq", "gemini", "openai", "ollama")

ALIASES = {
    "claude": "anthropic",
    "google": "gemini",
    "google-gemini": "gemini",
    "local": "ollama",
    "openai-compatible": "custom",
}


@dataclass
class AIConfig:
    """Cấu hình một lần gọi AI."""

    provider: str = "auto"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    extra_models: list[dict[str, str]] = field(default_factory=list)
    custom_prompt: str = ""

    @classmethod
    def load(cls, settings: Any = None) -> "AIConfig":
        """Đọc cấu hình từ settings.json, biến môi trường là phương án bổ sung."""
        if settings is not None:
            get = settings.get
        else:
            get = lambda key, default="": ""  # noqa: E731

        return cls(
            provider=str(get("ai_provider", "") or os.environ.get("AI_PROVIDER", "auto")).strip(),
            model=str(get("ai_model", "") or os.environ.get("AI_MODEL", "")).strip(),
            api_key=str(get("ai_key", "") or "").strip(),
            base_url=str(get("ai_base_url", "") or os.environ.get("AI_BASE_URL", "")).strip(),
            extra_models=get("ai_extra_models", []) or [],
            custom_prompt=str(get("ai_custom_prompt", "") or "").strip(),
        )

    def _infer_provider(self) -> str:
        """Đoán provider khi người dùng để "Tự động" nhưng có key/base URL."""
        if not self.api_key and not self.base_url:
            return ""
        base = self.base_url.lower()
        for needle, provider in (
            ("openrouter", "openrouter"),
            ("groq", "groq"),
            ("googleapis", "gemini"),
            ("openai.com", "openai"),
            ("localhost:11434", "ollama"),
            ("127.0.0.1:11434", "ollama"),
        ):
            if needle in base:
                return provider
        return "anthropic" if self.api_key else ""

    def resolve(self) -> "AIConfig | None":
        """Trả về cấu hình đủ dùng, hoặc None nếu chưa có key/model."""
        provider = (self.provider or "auto").strip().lower()
        provider = ALIASES.get(provider, provider)

        if provider == "auto":
            inferred = self._infer_provider()
            if inferred:
                found = replace(self, provider=inferred).resolve()
                if found is not None:
                    return found
            for name in PROVIDER_ORDER:
                if name == "anthropic" and not (_env("ANTHROPIC_API_KEY") or self.api_key):
                    continue  # Claude có thể dùng phiên `ant auth login`, chỉ tự chọn khi có key
                if name == "ollama" and not self._ollama_reachable():
                    continue
                found = replace(self, provider=name, api_key="", base_url="").resolve()
                if found is not None:
                    return found
            return None

        preset = PROVIDERS.get(provider)
        if preset is None:
            return None

        key = self.api_key or _env(*ENV_KEYS.get(provider, ()))
        model = self.model or preset["model"]
        base = self.base_url or preset["base_url"]

        if provider != "anthropic" and provider in (
                "openai", "openrouter", "groq", "gemini", "custom") and not key:
            return None
        if provider == "custom" and not base:
            return None
        if not model:
            return None

        return replace(self, provider=provider, model=model, api_key=key, base_url=base)

    def _ollama_reachable(self) -> bool:
        """Chỉ tự chọn Ollama khi máy local đang chạy dịch vụ."""
        base = PROVIDERS["ollama"]["base_url"]
        parsed = urlparse(base if "://" in base else f"http://{base}")
        host = parsed.hostname or "localhost"
        port = parsed.port or 11434
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            return False

    @property
    def label(self) -> str:
        provider = ALIASES.get((self.provider or "").lower(), (self.provider or "").lower())
        name = PROVIDERS.get(provider, {}).get("label", provider or "AI")
        return f"{name} · {self.model}" if self.model else name


def status(settings: Any = None) -> str:
    """Chuỗi trạng thái ngắn để hiện trên giao diện."""
    config = AIConfig.load(settings).resolve()
    if config is None:
        return "AI: chưa cấu hình — dùng phương án dự phòng offline"
    return f"AI: {config.label}"


def chat_json(system: str, prompt: str, settings: Any = None,
              config: AIConfig | None = None, timeout: float = 90.0) -> dict:
    """Gọi model và ép kết quả thành dict JSON.

    Ném ``AIUnavailable`` khi chưa cấu hình hoặc model trả lỗi. Phía gọi nên
    bắt lỗi này để chuyển sang phương án offline.
    """
    resolved = (config or AIConfig.load(settings)).resolve()
    if resolved is None:
        raise AIUnavailable(
            "Chưa cấu hình model AI. Mở Cấu hình AI để chọn Claude, model free "
            "(OpenRouter/Groq/Gemini) hoặc Ollama.")

    configs = [resolved]
    for index, item in enumerate(resolved.extra_models, start=2):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider", "")).strip()
        model = str(item.get("model", "")).strip()
        if not provider or not model:
            continue
        extra = AIConfig(
            provider=provider,
            model=model,
            api_key=str(item.get("api_key", "")).strip(),
            base_url=str(item.get("base_url", "")).strip(),
        ).resolve()
        if extra is None:
            raise AIUnavailable(
                f"Model {index} ({provider} / {model}) chưa cấu hình được. "
                "Kiểm tra API key hoặc địa chỉ dịch vụ."
            )
        configs.append(extra)

    combined_system = system
    if resolved.custom_prompt:
        combined_system += "\n\nHƯỚNG DẪN RIÊNG CỦA NGƯỜI DÙNG:\n" + resolved.custom_prompt

    result: dict[str, Any] | None = None
    for index, model_config in enumerate(configs):
        stage_prompt = prompt
        stage_system = combined_system
        if index and result is not None:
            stage_prompt += (
                "\n\nKẾT QUẢ JSON CỦA MODEL TRƯỚC:\n"
                + json.dumps(result, ensure_ascii=False)
                + "\nHãy rà soát, sửa lỗi và giữ đúng yêu cầu/schema JSON ban đầu. "
                "Chỉ trả về JSON cuối cùng."
            )
            if index < len(configs) - 1:
                stage_system += "\nBạn đang rà soát kết quả trung gian; trả về bản JSON đã chỉnh sửa."
            else:
                stage_system += "\nBạn là model tổng hợp cuối; trả về kết quả JSON hoàn chỉnh nhất."

        if model_config.provider == "anthropic":
            text = _call_anthropic(model_config, stage_system, stage_prompt, timeout)
        elif model_config.provider == "ollama":
            text = _call_ollama(model_config, stage_system, stage_prompt, timeout)
        else:
            text = _call_openai_compatible(model_config, stage_system, stage_prompt, timeout)
        result = _parse_json(text)

    return result or {}


# ---------------------------------------------------------------- Anthropic
def _call_anthropic(config: AIConfig, system: str, prompt: str, timeout: float = 90.0) -> str:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - phụ thuộc môi trường
        raise AIUnavailable("Chưa cài thư viện anthropic (pip install anthropic)") from exc

    try:
        client = anthropic.Anthropic(api_key=config.api_key or None, timeout=timeout)
        message = client.messages.create(
            model=config.model,
            max_tokens=4000,
            temperature=0.8,
            system=system + "\nChỉ trả về một đối tượng JSON hợp lệ, không thêm markdown.",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise AIUnavailable(f"Claude lỗi: {exc}") from exc

    text = "\n".join(block.text for block in message.content
                     if getattr(block, "type", "") == "text")
    if not text.strip():
        raise AIUnavailable("Claude không trả về nội dung")
    return text


# ------------------------------------------------------- OpenAI-compatible
def _call_openai_compatible(config: AIConfig, system: str, prompt: str, timeout: float) -> str:
    url = config.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }
    if config.provider == "openrouter":
        headers["HTTP-Referer"] = "https://capcut-tool.local"
        headers["X-Title"] = "CapCut Template Tool"

    body: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system + "\nChỉ trả về một đối tượng JSON hợp lệ, không thêm markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    try:
        data = _post_json(url, body, headers, timeout)
    except AIUnavailable as exc:
        # Một số model free không hỗ trợ response_format; thử lại ở chế độ thường.
        if "response_format" not in str(exc).lower():
            raise
        body.pop("response_format", None)
        data = _post_json(url, body, headers, timeout)

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIUnavailable(f"Phản hồi AI không đúng dạng: {str(data)[:300]}") from exc
    if isinstance(content, list):  # một số API trả về mảng block
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not str(content).strip():
        raise AIUnavailable("AI không trả về nội dung")
    return str(content)


# ------------------------------------------------------------------ Ollama
def _call_ollama(config: AIConfig, system: str, prompt: str, timeout: float) -> str:
    base = config.base_url.rstrip("/")
    url = base + "/api/chat"
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system + "\nChỉ trả về một đối tượng JSON hợp lệ, không thêm markdown."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.8},
    }
    data = _post_json(url, body, {}, timeout)
    content = data.get("message", {}).get("content", "")
    if not str(content).strip():
        raise AIUnavailable("Ollama không trả về nội dung")
    return str(content)


# ------------------------------------------------------------------ helpers
def _post_json(url: str, body: dict, headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise AIUnavailable(f"HTTP {exc.code} từ {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AIUnavailable(f"Không kết nối được {url}: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise AIUnavailable(f"Không kết nối được {url}: {exc}") from exc

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise AIUnavailable(f"Phản hồi không phải JSON: {raw[:300]}") from exc
    if not isinstance(data, dict):
        raise AIUnavailable(f"Phản hồi không đúng dạng: {str(data)[:300]}")
    return data


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            raise AIUnavailable(f"AI không trả về JSON: {text[:300]}")
        try:
            data = json.loads(match.group(0))
        except ValueError as exc:
            raise AIUnavailable(f"JSON của AI không hợp lệ: {text[:300]}") from exc
    if not isinstance(data, dict):
        raise AIUnavailable(f"AI trả về {type(data).__name__}, cần một object JSON")
    return data
