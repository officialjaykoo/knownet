import asyncio

from knownet_api.services.draft_service import DRAFT_JSON_SCHEMA, DraftService, StructuredDraft


def test_mock_draft_uses_structured_schema():
    service = DraftService(api_key=None, model="gpt-5-mini", timeout_seconds=1)

    result = asyncio.run(
        service.create_draft(
            message_id="msg_1",
            content="NEAT input feature growth test",
            title="NEAT input feature growth test",
        )
    )

    assert isinstance(result.structured, StructuredDraft)
    assert result.provider == "mock"
    assert result.structured.claims[0].source_keys == ["msg_1"]
    assert "## Claims" in result.markdown
    assert "[^msg_1]" in result.markdown


def test_draft_json_schema_is_strict():
    assert DRAFT_JSON_SCHEMA["additionalProperties"] is False
    assert set(DRAFT_JSON_SCHEMA["required"]) == {
        "title",
        "summary",
        "question",
        "claims",
        "evidence",
        "actions",
        "links",
        "citations",
    }
    claim_schema = DRAFT_JSON_SCHEMA["properties"]["claims"]["items"]
    assert claim_schema["additionalProperties"] is False
    assert "confidence" in claim_schema["required"]


def test_openai_draft_uses_responses_api_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "output_text": (
                    '{"title":"Draft","summary":"ok","question":"q","claims":[],'
                    '"evidence":[],"actions":[],"links":[],"citations":[]}'
                )
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

    monkeypatch.setattr("knownet_api.services.draft_service.httpx.AsyncClient", FakeAsyncClient)
    service = DraftService(
        api_key="test-openai-key",
        base_url="https://api.openai.com/v1",
        model="gpt-5-mini",
        reasoning_effort="low",
        max_output_tokens=2000,
        timeout_seconds=12,
    )
    result = asyncio.run(service.create_draft(message_id="msg_1", content="hello", title="Hello"))

    assert result.provider == "openai"
    assert result.model == "gpt-5-mini"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer test-openai-key"
    payload = captured["json"]
    assert payload["model"] == "gpt-5-mini"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["max_output_tokens"] == 2000
