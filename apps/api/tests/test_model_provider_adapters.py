import json
import re

from knownet_api.services.model_providers import (
    DeepSeekApiAdapter,
    GlmApiAdapter,
    KimiApiAdapter,
    MiniMaxApiAdapter,
    QwenApiAdapter,
    build_openai_compatible_review_messages,
)


def test_openai_compatible_prompt_includes_protocol_header():
    messages = build_openai_compatible_review_messages(
        {
            "request": {"review_focus": "protocol check"},
            "context": {"protocols": {"access_fallback": "inline"}, "stale_suppression": {"do_not_repeat_existing_titles": []}},
        },
        provider_name="DeepSeek",
    )
    system_prompt = messages[0]["content"]
    assert "access_fallback" in system_prompt
    assert "boundary_enforcement" in system_prompt
    assert "stale_suppression" in system_prompt
    assert "avoid full release_check" in system_prompt


def test_gemini_adapter_uses_documented_generate_content_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"review_title":"Gemini docs payload","overall_assessment":"ok","findings":[],"summary":"ok"}'
                                }
                            ]
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("knownet_api.services.model_providers.httpx.AsyncClient", FakeAsyncClient)
    from knownet_api.services.model_providers import GeminiApiAdapter

    adapter = GeminiApiAdapter(
        api_key="test-gemini-key",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-flash",
        response_mime_type="application/json",
        thinking_budget=0,
        timeout_seconds=12,
    )
    request = {"context": {"pages": []}, "request": {"mock": False, "review_focus": "payload"}}

    import asyncio

    result = asyncio.run(adapter.generate_review(request))
    assert result["review_title"] == "Gemini docs payload"
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    assert captured["headers"]["x-goog-api-key"] == "test-gemini-key"
    generation_config = captured["json"]["generationConfig"]
    assert generation_config["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in generation_config
    assert "responseSchema" not in generation_config
    assert generation_config["thinkingConfig"] == {"thinkingBudget": 0}


def test_deepseek_adapter_uses_documented_openai_compatible_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"review_title":"DeepSeek docs payload","overall_assessment":"ok","findings":[],"summary":"ok"}'
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("knownet_api.services.model_providers.httpx.AsyncClient", FakeAsyncClient)
    adapter = DeepSeekApiAdapter(
        api_key="test-deepseek-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        reasoning_effort="high",
        thinking_enabled=True,
        timeout_seconds=12,
    )
    request = {"context": {"pages": []}, "request": {"mock": False, "review_focus": "payload"}}

    import asyncio

    result = asyncio.run(adapter.generate_review(request))
    assert result["review_title"] == "DeepSeek docs payload"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-deepseek-key"
    assert captured["json"]["model"] == "deepseek-v4-pro"
    assert captured["json"]["stream"] is False
    assert captured["json"]["reasoning_effort"] == "high"
    assert captured["json"]["thinking"] == {"type": "enabled"}


def test_minimax_adapter_uses_documented_openai_compatible_payload(monkeypatch):
    captured = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"review_title":"MiniMax docs payload","overall_assessment":"ok","findings":[],"summary":"ok"}'
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("knownet_api.services.model_providers.httpx.AsyncClient", FakeAsyncClient)
    adapter = MiniMaxApiAdapter(
        api_key="test-minimax-key",
        base_url="https://api.minimaxi.com/v1",
        model="MiniMax-M2.7",
        max_tokens=4000,
        reasoning_split=True,
        timeout_seconds=12,
    )
    request = {"context": {"pages": []}, "request": {"mock": False, "review_focus": "payload"}}

    import asyncio

    result = asyncio.run(adapter.generate_review(request))
    assert result["review_title"] == "MiniMax docs payload"
    assert captured[0]["url"] == "https://api.minimaxi.com/v1/chat/completions"
    assert captured[0]["headers"]["Authorization"] == "Bearer test-minimax-key"
    payload = captured[0]["json"]
    assert payload["model"] == "MiniMax-M2.7"
    assert payload["stream"] is False
    assert payload["max_tokens"] == 4000
    assert payload["reasoning_split"] is True
    assert payload["tools"]


def test_qwen_adapter_uses_dashscope_openai_compatible_payload(monkeypatch):
    captured = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"review_title":"Qwen docs payload","overall_assessment":"ok","findings":[],"summary":"ok"}'
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("knownet_api.services.model_providers.httpx.AsyncClient", FakeAsyncClient)
    adapter = QwenApiAdapter(
        api_key="test-qwen-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        max_tokens=4000,
        enable_search=False,
        timeout_seconds=12,
    )
    request = {"context": {"pages": []}, "request": {"mock": False, "review_focus": "payload"}}

    import asyncio

    result = asyncio.run(adapter.generate_review(request))
    assert result["review_title"] == "Qwen docs payload"
    assert captured[0]["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert captured[0]["headers"]["Authorization"] == "Bearer test-qwen-key"
    payload = captured[0]["json"]
    assert payload["model"] == "qwen-plus"
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 4000
    assert "enable_search" not in payload
    assert payload["tools"]


def test_kimi_adapter_uses_documented_openai_compatible_payload(monkeypatch):
    captured = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"review_title":"Kimi docs payload","overall_assessment":"ok","findings":[],"summary":"ok"}'
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("knownet_api.services.model_providers.httpx.AsyncClient", FakeAsyncClient)
    adapter = KimiApiAdapter(
        api_key="test-kimi-key",
        base_url="https://api.moonshot.ai/v1",
        model="kimi-k2.5",
        max_tokens=4000,
        thinking_enabled=False,
        timeout_seconds=12,
    )
    request = {"context": {"pages": []}, "request": {"mock": False, "review_focus": "payload"}}

    import asyncio

    result = asyncio.run(adapter.generate_review(request))
    assert result["review_title"] == "Kimi docs payload"
    assert captured[0]["url"] == "https://api.moonshot.ai/v1/chat/completions"
    assert captured[0]["headers"]["Authorization"] == "Bearer test-kimi-key"
    payload = captured[0]["json"]
    assert payload["model"] == "kimi-k2.5"
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 4000
    assert payload["thinking"] == {"type": "disabled"}
    assert "temperature" not in payload
    assert "max_completion_tokens" not in payload


def test_glm_adapter_uses_zai_openai_compatible_payload(monkeypatch):
    captured = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"review_title":"GLM docs payload","overall_assessment":"ok","findings":[],"summary":"ok"}'
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("knownet_api.services.model_providers.httpx.AsyncClient", FakeAsyncClient)
    adapter = GlmApiAdapter(
        api_key="test-glm-key",
        base_url="https://api.z.ai/api/paas/v4",
        model="glm-5.1",
        max_tokens=4000,
        thinking_enabled=False,
        timeout_seconds=12,
    )
    request = {"context": {"pages": []}, "request": {"mock": False, "review_focus": "payload"}}

    import asyncio

    result = asyncio.run(adapter.generate_review(request))
    assert result["review_title"] == "GLM docs payload"
    assert captured[0]["url"] == "https://api.z.ai/api/paas/v4/chat/completions"
    assert captured[0]["headers"]["Authorization"] == "Bearer test-glm-key"
    payload = captured[0]["json"]
    assert payload["model"] == "glm-5.1"
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 4000
    assert "thinking" not in payload
    assert payload["tools"]

