from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    api_key_env: str
    base_url_env: str
    model_env: str
    default_base_url: str
    default_model: str
    endpoint: str
    native_gemini: bool = False


PROVIDERS: dict[str, ProviderProfile] = {
    "openai": ProviderProfile("openai", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "https://api.openai.com/v1", "gpt-5-mini", "/responses"),
    "deepseek": ProviderProfile("deepseek", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "https://api.deepseek.com", "deepseek-v4-flash", "/chat/completions"),
    "minimax": ProviderProfile("minimax", "MINIMAX_API_KEY", "MINIMAX_BASE_URL", "MINIMAX_MODEL", "https://api.minimaxi.com/v1", "MiniMax-M2.7", "/chat/completions"),
    "qwen": ProviderProfile("qwen", "QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", "/chat/completions"),
    "kimi": ProviderProfile("kimi", "KIMI_API_KEY", "KIMI_BASE_URL", "KIMI_MODEL", "https://api.moonshot.ai/v1", "kimi-k2.5", "/chat/completions"),
    "glm": ProviderProfile("glm", "GLM_API_KEY", "GLM_BASE_URL", "GLM_MODEL", "https://api.z.ai/api/paas/v4", "glm-5.1", "/chat/completions"),
    "gemini": ProviderProfile("gemini", "GEMINI_API_KEY", "GEMINI_BASE_URL", "GEMINI_MODEL", "https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash", "", native_gemini=True),
}


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def openai_compatible_payload(provider: str, model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": 'Reply with {"ok": true, "provider": "' + provider + '"}.'},
        ],
        "stream": False,
        "temperature": 0,
    }
    if provider in {"qwen", "kimi", "glm"}:
        payload["response_format"] = {"type": "json_object"}
    if provider == "deepseek":
        payload["reasoning_effort"] = os.getenv("DEEPSEEK_REASONING_EFFORT", "high")
        payload["thinking"] = {"type": "enabled" if env_bool("DEEPSEEK_THINKING_ENABLED", True) else "disabled"}
    elif provider == "minimax":
        payload["max_tokens"] = env_int("MINIMAX_MAX_TOKENS", 4000)
        if env_bool("MINIMAX_REASONING_SPLIT", True):
            payload["reasoning_split"] = True
    elif provider == "qwen":
        payload["max_tokens"] = env_int("QWEN_MAX_TOKENS", 4000)
        if env_bool("QWEN_ENABLE_SEARCH", False):
            payload["enable_search"] = True
    elif provider == "kimi":
        payload["max_tokens"] = env_int("KIMI_MAX_TOKENS", 4000)
        payload["thinking"] = {"type": "enabled" if env_bool("KIMI_THINKING_ENABLED", False) else "disabled"}
    elif provider == "glm":
        payload["max_tokens"] = env_int("GLM_MAX_TOKENS", 4000)
        if env_bool("GLM_THINKING_ENABLED", False):
            payload["thinking"] = {"type": "enabled"}
    return payload


def openai_responses_payload(model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "instructions": "Return JSON only.",
        "input": "Reply with {\"ok\": true, \"provider\": \"openai\"}.",
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": env_int("OPENAI_MAX_OUTPUT_TOKENS", 2000),
    }
    effort = os.getenv("OPENAI_REASONING_EFFORT", "low").strip()
    if effort:
        payload["reasoning"] = {"effort": effort}
    return payload


def gemini_payload() -> dict[str, Any]:
    generation_config: dict[str, Any] = {
        "temperature": 0,
        "responseMimeType": os.getenv("GEMINI_RESPONSE_MIME_TYPE", "application/json"),
    }
    thinking_budget = os.getenv("GEMINI_THINKING_BUDGET")
    if thinking_budget is not None and thinking_budget.strip():
        generation_config["thinkingConfig"] = {"thinkingBudget": int(thinking_budget)}
    return {
        "contents": [{"role": "user", "parts": [{"text": 'Reply with {"ok": true, "provider": "gemini"}.'}]}],
        "generationConfig": generation_config,
    }


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def request_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"status": response.status, "body": json.loads(body)}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return {"status": error.code, "body": safe_json(body)}


def safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:1000]


def run_provider(provider: str, timeout: float, dry_run: bool) -> int:
    profile = PROVIDERS[provider]
    api_key = os.getenv(profile.api_key_env, "").strip()
    base_url = os.getenv(profile.base_url_env, profile.default_base_url).strip().rstrip("/")
    model = os.getenv(profile.model_env, profile.default_model).strip()
    if not api_key and not dry_run:
        print(f"{provider}: missing {profile.api_key_env}")
        return 2

    if profile.native_gemini:
        url = f"{base_url}/models/{model}:generateContent"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        payload = gemini_payload()
    elif provider == "openai":
        url = f"{base_url}{profile.endpoint}"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = openai_responses_payload(model)
    else:
        url = f"{base_url}{profile.endpoint}"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = openai_compatible_payload(provider, model)

    print(json.dumps({"provider": provider, "url": url, "model": model, "api_key": "<configured>" if api_key else None, "dry_run": dry_run}, indent=2))
    if dry_run:
        print(json.dumps({"payload": payload}, indent=2, ensure_ascii=False))
        return 0

    result = request_json(url, headers, payload, timeout)
    status = int(result["status"])
    print(json.dumps({"status": status, "body": result["body"]}, indent=2, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test provider API keys and official request shapes without touching KnowNet data.")
    parser.add_argument("provider", choices=sorted(PROVIDERS))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true", help="Print URL and payload without calling the provider.")
    args = parser.parse_args()
    load_dotenv(args.env_file)
    return run_provider(args.provider, args.timeout, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
