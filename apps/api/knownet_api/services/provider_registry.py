from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Settings


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    label: str
    route_type: str
    implemented_surface: str
    compatibility_class: str
    openai_compatible: bool
    anthropic_compatible: bool = False
    custom_api: bool = False
    reasoning_options: tuple[str, ...] = ()
    safe_scopes: tuple[str, ...] = ("safe_context", "dry_run", "operator_import")
    known_limitations: tuple[str, ...] = ()
    local_test_command: str = "pytest tests/test_phase16_model_runner.py -q"
    live_route: str | None = None


PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        provider_id="gemini",
        label="Gemini API",
        route_type="server_model_runner",
        implemented_surface="api_adapter",
        compatibility_class="custom_api",
        openai_compatible=False,
        custom_api=True,
        reasoning_options=("thinking_budget",),
        known_limitations=("live_verified requires a real API call; free tier may rate-limit", "official API is not OpenAI-compatible"),
        live_route="POST /api/model-runs/gemini/reviews {mock:false}",
    ),
    ProviderDefinition(
        provider_id="deepseek",
        label="DeepSeek API",
        route_type="server_model_runner",
        implemented_surface="api_adapter",
        compatibility_class="openai_compatible_with_overrides",
        openai_compatible=True,
        anthropic_compatible=True,
        reasoning_options=("reasoning_effort", "thinking"),
        known_limitations=("web chat is fallback only", "reasoning/thinking options are provider-specific"),
        live_route="POST /api/model-runs/deepseek/reviews {mock:false}",
    ),
    ProviderDefinition(
        provider_id="qwen",
        label="Qwen/DashScope API",
        route_type="server_model_runner",
        implemented_surface="api_adapter",
        compatibility_class="openai_compatible_with_overrides",
        openai_compatible=True,
        reasoning_options=("enable_search",),
        known_limitations=("Qwen-Agent MCP remains separate", "DashScope compatible mode has provider-specific options"),
        live_route="POST /api/model-runs/qwen/reviews {mock:false}",
    ),
    ProviderDefinition(
        provider_id="kimi",
        label="Kimi API",
        route_type="server_model_runner",
        implemented_surface="api_adapter",
        compatibility_class="openai_compatible_with_overrides",
        openai_compatible=True,
        reasoning_options=("thinking",),
        known_limitations=("Kimi Code MCP remains separate", "thinking option is provider-specific"),
        live_route="POST /api/model-runs/kimi/reviews {mock:false}",
    ),
    ProviderDefinition(
        provider_id="minimax",
        label="MiniMax API",
        route_type="server_model_runner",
        implemented_surface="api_adapter",
        compatibility_class="openai_compatible_with_overrides",
        openai_compatible=True,
        reasoning_options=("reasoning_split",),
        known_limitations=("Mini-Agent remains separate", "reasoning split is provider-specific"),
        live_route="POST /api/model-runs/minimax/reviews {mock:false}",
    ),
    ProviderDefinition(
        provider_id="glm",
        label="GLM/Z.AI API",
        route_type="server_model_runner",
        implemented_surface="api_adapter",
        compatibility_class="openai_compatible_with_overrides",
        openai_compatible=True,
        reasoning_options=("thinking",),
        known_limitations=("coding-tool MCP remains separate", "thinking option is provider-specific"),
        live_route="POST /api/model-runs/glm/reviews {mock:false}",
    ),
    ProviderDefinition(
        provider_id="mock",
        label="Local mock runner",
        route_type="server_model_runner",
        implemented_surface="mock_adapter",
        compatibility_class="custom_api",
        openai_compatible=False,
        custom_api=True,
        safe_scopes=("safe_context", "dry_run"),
        known_limitations=("mock only; never live_verified",),
    ),
)


def provider_capability(definition: ProviderDefinition, settings: Settings) -> dict[str, Any]:
    prefix = definition.provider_id
    model = getattr(settings, f"{prefix}_model", None) if prefix != "mock" else "mock"
    base_url = getattr(settings, f"{prefix}_base_url", None) if prefix != "mock" else None
    timeout = getattr(settings, f"{prefix}_timeout_seconds", None) if prefix != "mock" else None
    enabled = bool(getattr(settings, f"{prefix}_runner_enabled", True)) if prefix != "mock" else True
    has_credentials = bool(getattr(settings, f"{prefix}_api_key", True)) if prefix != "mock" else True
    return {
        "provider_id": definition.provider_id,
        "label": definition.label,
        "route_type": definition.route_type,
        "implemented_surface": definition.implemented_surface,
        "compatibility_class": definition.compatibility_class,
        "openai_compatible": definition.openai_compatible,
        "anthropic_compatible": definition.anthropic_compatible,
        "custom_api": definition.custom_api,
        "base_url": base_url,
        "model": model,
        "timeout_seconds": timeout,
        "reasoning_options": list(definition.reasoning_options),
        "enabled": enabled,
        "has_credentials": has_credentials,
        "required_config_present": bool(enabled and has_credentials),
        "safe_scopes": list(definition.safe_scopes),
        "known_limitations": list(definition.known_limitations),
        "local_test_command": definition.local_test_command,
        "live_test_command": definition.live_route,
    }


def provider_capabilities(settings: Settings) -> list[dict[str, Any]]:
    return [provider_capability(definition, settings) for definition in PROVIDER_DEFINITIONS]


def provider_capability_map(settings: Settings) -> dict[str, dict[str, Any]]:
    return {item["provider_id"]: item for item in provider_capabilities(settings)}

