from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

from .model_output import extract_json_object_text, sanitize_error_message, strip_think_tags


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class GeminiMockAdapter:
    provider_id = "gemini"

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context") or {}
        summary = context.get("summary") or {}
        pages = context.get("pages") or []
        findings = context.get("open_findings") or []
        page_count = summary.get("pages", len(pages)) if isinstance(summary, dict) else len(pages)
        stale_hint = "No active ai_state pages were included." if not pages else f"{len(pages)} ai_state pages were sampled."
        return {
            "review_title": "Gemini mock review of KnowNet model context",
            "overall_assessment": "Gemini mock adapter verified that the shared model-runner context can be built, sanitized, parsed, and held for operator import.",
            "findings": [
                {
                    "title": "Model runner context should stay bounded and sanitized",
                    "severity": "medium",
                    "area": "API",
                    "evidence": f"The mock run received page_count={page_count}, sampled_pages={len(pages)}, open_findings={len(findings)}. {stale_hint}",
                    "proposed_change": "Keep Phase 16 provider adapters behind the shared safe context builder and block direct provider-specific data assembly.",
                    "confidence": 0.84,
                },
                {
                    "title": "Operator import gate should remain mandatory",
                    "severity": "low",
                    "area": "Ops",
                    "evidence": "The mock provider returned findings as dry-run-ready review Markdown instead of creating collaboration records directly.",
                    "proposed_change": "Require an explicit operator import action for every external model result, including future paid providers.",
                    "confidence": 0.78,
                },
            ],
            "summary": "Mock result only. No Gemini network call was made.",
        }


class MockModelReviewAdapter:
    def __init__(self, *, provider_id: str) -> None:
        self.provider_id = provider_id

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context") or {}
        summary = context.get("summary") or {}
        pages = context.get("pages") or []
        findings = context.get("open_findings") or []
        page_count = summary.get("pages", len(pages)) if isinstance(summary, dict) else len(pages)
        return {
            "review_title": f"{self.provider_id.title()} mock review of KnowNet model context",
            "overall_assessment": "Mock adapter verified that this provider path can build sanitized context, parse model-shaped JSON, and stop at dry-run.",
            "findings": [
                {
                    "title": f"{self.provider_id.title()} provider path should keep operator import mandatory",
                    "severity": "low",
                    "area": "Ops",
                    "evidence": f"The mock run received page_count={page_count}, sampled_pages={len(pages)}, open_findings={len(findings)} and returned dry-run-ready data only.",
                    "proposed_change": "Keep the shared model-runner dry-run and operator import gate for every provider.",
                    "confidence": 0.8,
                }
            ],
            "summary": "Mock result only. No provider network call was made.",
        }


GEMINI_REVIEW_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "review_title": {"type": "STRING"},
        "overall_assessment": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "findings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "severity": {"type": "STRING", "enum": ["critical", "high", "medium", "low", "info"]},
                    "area": {"type": "STRING", "enum": ["API", "UI", "Rust", "Security", "Data", "Ops", "Docs"]},
                    "evidence": {"type": "STRING"},
                    "proposed_change": {"type": "STRING"},
                    "confidence": {"type": "NUMBER"},
                },
                "required": ["title", "severity", "area", "evidence", "proposed_change"],
                "propertyOrdering": ["title", "severity", "area", "evidence", "proposed_change", "confidence"],
            },
        },
    },
    "required": ["review_title", "overall_assessment", "summary", "findings"],
    "propertyOrdering": ["review_title", "overall_assessment", "findings", "summary"],
}


def build_gemini_review_prompt(request: dict[str, Any]) -> str:
    run_request = request.get("request") or {}
    context = request.get("context") or {}
    focus = run_request.get("review_focus") or "Review the current KnowNet state for concrete risks that should be fixed before broader external AI use."
    return "\n".join(
        [
            "You are an external AI reviewer for KnowNet.",
            "KnowNet is an AI collaboration knowledge base. You receive a sanitized, structured context snapshot only.",
            "",
            "Rules:",
            "- Return JSON only, matching the requested schema.",
            "- Follow contract_version and output_contract in the supplied packet contract. If unsupported, escalate instead of guessing.",
            "- Do not ask for raw database files, local filesystem paths, secrets, backups, sessions, users, or raw tokens.",
            "- Apply the provided access_fallback and boundary_enforcement protocols before making recommendations.",
            "- Do not repeat stale or duplicate findings listed under stale_suppression unless the new proposed change is materially different.",
            "- Focus on actionable implementation, API, data, security, ops, or docs findings.",
            "- Prefer 1 to 5 high-signal findings. Do not invent facts beyond the provided context.",
            "- Evidence must cite fields or observations from the provided context, not private assumptions.",
            "- Proposed change must be concrete enough for Codex to implement or verify.",
            "- Prefer targeted tests/API smoke checks for daily iteration; avoid full release_check unless release verification is requested.",
            "",
            f"Review focus: {focus}",
            "",
            "Sanitized KnowNet context JSON:",
            _json_dumps(context),
        ]
    )


class GeminiApiAdapter:
    provider_id = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str,
        response_mime_type: str = "application/json",
        thinking_budget: int | None = 0,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.response_mime_type = response_mime_type
        self.thinking_budget = thinking_budget
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = build_gemini_review_prompt(request)
        url = f"{self.base_url}/models/{self.model}:generateContent"
        generation_config: dict[str, Any] = {
            "temperature": 0.2,
            "responseMimeType": self.response_mime_type,
            "responseJsonSchema": GEMINI_REVIEW_RESPONSE_SCHEMA,
        }
        if self.thinking_budget is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(
                status_code=504,
                detail={"code": "gemini_timeout", "message": "Gemini API request timed out", "details": {}},
            ) from error
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "gemini_request_failed", "message": sanitize_error_message(str(error)), "details": {}},
            ) from error

        if response.status_code >= 400:
            message = _extract_gemini_error_message(response)
            if response.status_code == 429:
                code = "gemini_rate_limited"
            elif response.status_code in {401, 403}:
                code = "gemini_auth_failed"
            else:
                code = "gemini_request_failed"
            raise HTTPException(
                status_code=502,
                detail={"code": code, "message": sanitize_error_message(message) or "Gemini API request failed", "details": {"status_code": response.status_code}},
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "gemini_invalid_response", "message": "Gemini API response was not JSON", "details": {}},
            ) from error

        text = _extract_gemini_text(payload)
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "gemini_invalid_response", "message": "Gemini API response text was not valid JSON", "details": {}},
            ) from error


def _extract_gemini_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text[:1000]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(payload)[:1000]


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise HTTPException(status_code=502, detail={"code": "gemini_invalid_response", "message": "Gemini API returned no candidates", "details": {}})
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise HTTPException(status_code=502, detail={"code": "gemini_invalid_response", "message": "Gemini API candidate has no parts", "details": {}})
    text_parts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    text = "".join(text_parts).strip()
    if not text:
        raise HTTPException(status_code=502, detail={"code": "gemini_invalid_response", "message": "Gemini API returned empty text", "details": {}})
    return text


def build_openai_compatible_review_messages(request: dict[str, Any], *, provider_name: str) -> list[dict[str, str]]:
    run_request = request.get("request") or {}
    context = request.get("context") or {}
    focus = run_request.get("review_focus") or "Review the current KnowNet state for concrete risks that should be fixed before broader external AI use."
    example = {
        "review_title": f"{provider_name} review of KnowNet",
        "overall_assessment": "Brief assessment.",
        "findings": [
            {
                "title": "Concrete issue title",
                "severity": "medium",
                "area": "API",
                "evidence": "Specific evidence from the provided context.",
                "proposed_change": "Specific change to make.",
                "confidence": 0.8,
            }
        ],
        "summary": "Short summary.",
    }
    system_prompt = "\n".join(
        [
            f"You are {provider_name}, acting as an external AI reviewer for KnowNet.",
            "Return strict JSON only. The word json is intentionally included for JSON mode.",
            "Do not request or reveal raw database files, local filesystem paths, secrets, backups, sessions, users, raw tokens, or token hashes.",
            "Use only the provided sanitized context.",
            "Apply the provided access_fallback and boundary_enforcement protocols before making recommendations.",
            "Do not repeat stale or duplicate findings listed under stale_suppression unless the new proposed change is materially different.",
            "Prefer targeted tests/API smoke checks for daily iteration; avoid full release_check unless release verification is requested.",
            "Severity must be one of: critical, high, medium, low, info.",
            "Area must be one of: API, UI, Rust, Security, Data, Ops, Docs.",
            "Output JSON must follow this example shape:",
            json.dumps(example, ensure_ascii=False),
        ]
    )
    user_prompt = "\n".join(
        [
            f"Review focus: {focus}",
            "Prefer 1 to 5 high-signal findings. If no issue exists, return one low/info finding explaining the remaining verification gap.",
            "Sanitized KnowNet context JSON:",
            _json_dumps(context),
        ]
    )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


MINIMAX_KNOWNET_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "knownet_state_summary",
            "description": "Read the sanitized KnowNet state summary already prepared for this model run.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knownet_ai_state",
            "description": "Read sampled sanitized ai_state pages from the prepared model-run context.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knownet_list_findings",
            "description": "Read open findings from the prepared model-run context.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}},
                "additionalProperties": False,
            },
        },
    },
]

KIMI_KNOWNET_TOOLS = MINIMAX_KNOWNET_TOOLS
QWEN_KNOWNET_TOOLS = MINIMAX_KNOWNET_TOOLS
GLM_KNOWNET_TOOLS = MINIMAX_KNOWNET_TOOLS


def _execute_knownet_context_tool(context: dict[str, Any], name: str, arguments_json: str | None, *, provider_code: str, provider_name: str) -> dict[str, Any]:
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_tool_args", "message": f"{provider_name} returned invalid tool arguments", "details": {"tool": name}})
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_tool_args", "message": f"{provider_name} tool arguments must be a JSON object", "details": {"tool": name}})
    if name == "knownet_state_summary":
        return {"summary": context.get("summary") or {}, "rules": context.get("rules") or {}}
    if name == "knownet_ai_state":
        limit = min(max(int(arguments.get("limit") or 10), 1), 20)
        return {"pages": (context.get("pages") or [])[:limit], "returned_count": len((context.get("pages") or [])[:limit])}
    if name == "knownet_list_findings":
        limit = min(max(int(arguments.get("limit") or 20), 1), 50)
        findings = context.get("open_findings") or []
        return {"findings": findings[:limit], "returned_count": len(findings[:limit])}
    raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_tool", "message": f"{provider_name} requested a tool that is not allowed", "details": {"tool": name}})


class DeepSeekApiAdapter:
    provider_id = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str,
        reasoning_effort: str | None = "high",
        thinking_enabled: bool = True,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.thinking_enabled = thinking_enabled
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": build_openai_compatible_review_messages(request, provider_name="DeepSeek"),
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 4000,
            "stream": False,
            "thinking": {"type": "enabled" if self.thinking_enabled else "disabled"},
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "deepseek_timeout", "message": "DeepSeek API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "deepseek_request_failed", "message": sanitize_error_message(str(error)), "details": {}},
            ) from error

        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "deepseek_rate_limited"
            elif response.status_code in {401, 403}:
                code = "deepseek_auth_failed"
            else:
                code = "deepseek_request_failed"
            raise HTTPException(
                status_code=502,
                detail={"code": code, "message": sanitize_error_message(message) or "DeepSeek API request failed", "details": {"status_code": response.status_code}},
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "deepseek_invalid_response", "message": "DeepSeek API response was not JSON", "details": {}}) from error

        text = _extract_openai_compatible_message_content(payload, provider_code="deepseek")
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "deepseek_invalid_response", "message": "DeepSeek API response content was not valid JSON", "details": {}}) from error


class MiniMaxApiAdapter:
    provider_id = "minimax"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 4000,
        reasoning_split: bool = True,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.reasoning_split = reasoning_split
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = build_openai_compatible_review_messages(request, provider_name="MiniMax")
        messages[0]["content"] += "\nYou may use the provided knownet_* tools for read-only context lookup. Final answer must be strict JSON only."
        body = {
            "model": self.model,
            "messages": messages,
            "tools": MINIMAX_KNOWNET_TOOLS,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.reasoning_split:
            body["reasoning_split"] = True
        first_payload = await self._post_chat(body)
        first_message = _extract_openai_compatible_message(first_payload, provider_code="minimax")
        tool_calls = first_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(first_message)
            context = request.get("context") or {}
            for tool_call in tool_calls[:5]:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments") if isinstance(function, dict) else None
                if not isinstance(name, str):
                    raise HTTPException(status_code=502, detail={"code": "minimax_invalid_tool", "message": "MiniMax returned a malformed tool call", "details": {}})
                tool_result = _execute_knownet_context_tool(context, name, arguments if isinstance(arguments, str) else "{}", provider_code="minimax", provider_name="MiniMax")
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": json.dumps(tool_result, ensure_ascii=False)})
            final_payload = await self._post_chat({**body, "messages": messages, "tools": MINIMAX_KNOWNET_TOOLS})
            final_message = _extract_openai_compatible_message(final_payload, provider_code="minimax")
            content = str(final_message.get("content") or "").strip()
        else:
            content = str(first_message.get("content") or "").strip()
        content = strip_think_tags(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            extracted = extract_json_object_text(content)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            raise HTTPException(status_code=502, detail={"code": "minimax_invalid_response", "message": "MiniMax API response content was not valid JSON", "details": {}}) from error

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "minimax_timeout", "message": "MiniMax API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail={"code": "minimax_request_failed", "message": sanitize_error_message(str(error)), "details": {}}) from error
        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "minimax_rate_limited"
            elif response.status_code in {401, 403}:
                code = "minimax_auth_failed"
            else:
                code = "minimax_request_failed"
            raise HTTPException(status_code=502, detail={"code": code, "message": sanitize_error_message(message) or "MiniMax API request failed", "details": {"status_code": response.status_code}})
        try:
            return response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "minimax_invalid_response", "message": "MiniMax API response was not JSON", "details": {}}) from error


class KimiApiAdapter:
    provider_id = "kimi"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 4000,
        thinking_enabled: bool = False,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.thinking_enabled = thinking_enabled
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = build_openai_compatible_review_messages(request, provider_name="Kimi/Moonshot")
        messages[0]["content"] += "\nYou may use the provided knownet_* tools for read-only context lookup. Final answer must be strict JSON only."
        body = {
            "model": self.model,
            "messages": messages,
            "tools": KIMI_KNOWNET_TOOLS,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
            "stream": False,
            "thinking": {"type": "enabled" if self.thinking_enabled else "disabled"},
        }
        first_payload = await self._post_chat(body)
        first_message = _extract_openai_compatible_message(first_payload, provider_code="kimi")
        tool_calls = first_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(first_message)
            context = request.get("context") or {}
            for tool_call in tool_calls[:5]:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments") if isinstance(function, dict) else None
                if not isinstance(name, str):
                    raise HTTPException(status_code=502, detail={"code": "kimi_invalid_tool", "message": "Kimi returned a malformed tool call", "details": {}})
                tool_result = _execute_knownet_context_tool(context, name, arguments if isinstance(arguments, str) else "{}", provider_code="kimi", provider_name="Kimi")
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": json.dumps(tool_result, ensure_ascii=False)})
            final_payload = await self._post_chat({**body, "messages": messages, "tools": KIMI_KNOWNET_TOOLS})
            final_message = _extract_openai_compatible_message(final_payload, provider_code="kimi")
            content = str(final_message.get("content") or "").strip()
        else:
            content = str(first_message.get("content") or "").strip()
        content = strip_think_tags(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            extracted = extract_json_object_text(content)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            raise HTTPException(status_code=502, detail={"code": "kimi_invalid_response", "message": "Kimi API response content was not valid JSON", "details": {}}) from error

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "kimi_timeout", "message": "Kimi API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail={"code": "kimi_request_failed", "message": sanitize_error_message(str(error)), "details": {}}) from error
        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "kimi_rate_limited"
            elif response.status_code in {401, 403}:
                code = "kimi_auth_failed"
            else:
                code = "kimi_request_failed"
            raise HTTPException(status_code=502, detail={"code": code, "message": sanitize_error_message(message) or "Kimi API request failed", "details": {"status_code": response.status_code}})
        try:
            return response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "kimi_invalid_response", "message": "Kimi API response was not JSON", "details": {}}) from error


class QwenApiAdapter:
    provider_id = "qwen"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 4000,
        enable_search: bool = False,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.enable_search = enable_search
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = build_openai_compatible_review_messages(request, provider_name="Qwen/DashScope")
        messages[0]["content"] += "\nYou may use the provided knownet_* tools for read-only context lookup. Final answer must be strict JSON only."
        body = {
            "model": self.model,
            "messages": messages,
            "tools": QWEN_KNOWNET_TOOLS,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.enable_search:
            body["enable_search"] = True
        first_payload = await self._post_chat(body)
        first_message = _extract_openai_compatible_message(first_payload, provider_code="qwen")
        tool_calls = first_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(first_message)
            context = request.get("context") or {}
            for tool_call in tool_calls[:5]:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments") if isinstance(function, dict) else None
                if not isinstance(name, str):
                    raise HTTPException(status_code=502, detail={"code": "qwen_invalid_tool", "message": "Qwen returned a malformed tool call", "details": {}})
                tool_result = _execute_knownet_context_tool(context, name, arguments if isinstance(arguments, str) else "{}", provider_code="qwen", provider_name="Qwen")
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": json.dumps(tool_result, ensure_ascii=False)})
            final_payload = await self._post_chat({**body, "messages": messages, "tools": QWEN_KNOWNET_TOOLS})
            final_message = _extract_openai_compatible_message(final_payload, provider_code="qwen")
            content = str(final_message.get("content") or "").strip()
        else:
            content = str(first_message.get("content") or "").strip()
        content = strip_think_tags(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            extracted = extract_json_object_text(content)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            raise HTTPException(status_code=502, detail={"code": "qwen_invalid_response", "message": "Qwen API response content was not valid JSON", "details": {}}) from error

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "qwen_timeout", "message": "Qwen API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail={"code": "qwen_request_failed", "message": sanitize_error_message(str(error)), "details": {}}) from error
        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "qwen_rate_limited"
            elif response.status_code in {401, 403}:
                code = "qwen_auth_failed"
            else:
                code = "qwen_request_failed"
            raise HTTPException(status_code=502, detail={"code": code, "message": sanitize_error_message(message) or "Qwen API request failed", "details": {"status_code": response.status_code}})
        try:
            return response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "qwen_invalid_response", "message": "Qwen API response was not JSON", "details": {}}) from error


class GlmApiAdapter:
    provider_id = "glm"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_tokens: int = 4000,
        thinking_enabled: bool = False,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.thinking_enabled = thinking_enabled
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = build_openai_compatible_review_messages(request, provider_name="GLM/Z.AI")
        messages[0]["content"] += "\nYou may use the provided knownet_* tools for read-only context lookup. Final answer must be strict JSON only."
        body = {
            "model": self.model,
            "messages": messages,
            "tools": GLM_KNOWNET_TOOLS,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.thinking_enabled:
            body["thinking"] = {"type": "enabled"}
        first_payload = await self._post_chat(body)
        first_message = _extract_openai_compatible_message(first_payload, provider_code="glm")
        tool_calls = first_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(first_message)
            context = request.get("context") or {}
            for tool_call in tool_calls[:5]:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments") if isinstance(function, dict) else None
                if not isinstance(name, str):
                    raise HTTPException(status_code=502, detail={"code": "glm_invalid_tool", "message": "GLM returned a malformed tool call", "details": {}})
                tool_result = _execute_knownet_context_tool(context, name, arguments if isinstance(arguments, str) else "{}", provider_code="glm", provider_name="GLM")
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": json.dumps(tool_result, ensure_ascii=False)})
            final_payload = await self._post_chat({**body, "messages": messages, "tools": GLM_KNOWNET_TOOLS})
            final_message = _extract_openai_compatible_message(final_payload, provider_code="glm")
            content = str(final_message.get("content") or "").strip()
        else:
            content = str(first_message.get("content") or "").strip()
        content = strip_think_tags(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            extracted = extract_json_object_text(content)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            raise HTTPException(status_code=502, detail={"code": "glm_invalid_response", "message": "GLM API response content was not valid JSON", "details": {}}) from error

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "glm_timeout", "message": "GLM API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail={"code": "glm_request_failed", "message": sanitize_error_message(str(error)), "details": {}}) from error
        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "glm_rate_limited"
            elif response.status_code in {401, 403}:
                code = "glm_auth_failed"
            else:
                code = "glm_request_failed"
            raise HTTPException(status_code=502, detail={"code": code, "message": sanitize_error_message(message) or "GLM API request failed", "details": {"status_code": response.status_code}})
        try:
            return response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "glm_invalid_response", "message": "GLM API response was not JSON", "details": {}}) from error


def _extract_openai_compatible_message(payload: dict[str, Any], *, provider_code: str) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_response", "message": "Provider returned no choices", "details": {}})
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_response", "message": "Provider returned no message", "details": {}})
    return message


def _extract_openai_compatible_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text[:1000]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(payload)[:1000]


def _extract_openai_compatible_message_content(payload: dict[str, Any], *, provider_code: str) -> str:
    message = _extract_openai_compatible_message(payload, provider_code=provider_code)
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_response", "message": "Provider returned empty message content", "details": {}})
    return content.strip()
