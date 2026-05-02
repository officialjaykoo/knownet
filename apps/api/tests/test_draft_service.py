import asyncio

from knownet_api.services.draft_service import DRAFT_JSON_SCHEMA, DraftService, StructuredDraft


def test_mock_draft_uses_structured_schema():
    service = DraftService(api_key=None, model="gpt-4o-mini", timeout_seconds=1)

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
