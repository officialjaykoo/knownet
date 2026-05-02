import asyncio
from pathlib import Path

from knownet_api.services.embedding_service import EmbeddingService


class FakeModel:
    def encode(self, text: str, normalize_embeddings: bool = True):
        assert normalize_embeddings is True
        return [0.1, 0.2, 0.3] if text else [0.0, 0.0, 0.0]


class FakeRust:
    def __init__(self) -> None:
        self.params = None

    async def request(self, cmd, params):
        assert cmd == "embedding_upsert"
        vector_path = Path(params["vector_path"])
        assert vector_path.exists()
        assert vector_path.stat().st_size == params["dims"] * 4
        self.params = params
        return {"embedding_id": params["embedding_id"], "status": "stored"}


def test_embedding_service_ready_with_fake_model(tmp_path):
    service = EmbeddingService("fake-model", model=FakeModel())

    health = service.health()
    assert health["status"] == "ready"

    rust = FakeRust()
    result = asyncio.run(service.upsert_text(
        rust=rust,
        sqlite_path=tmp_path / "knownet.db",
        tmp_dir=tmp_path,
        owner_type="message",
        owner_id="msg_1",
        text="NEAT input feature growth test",
        updated_at="2026-05-01T00:00:00Z",
    ))

    assert result["stored"] is True
    assert result["dims"] == 3
    assert rust.params is not None
    assert rust.params["owner_type"] == "message"
    assert not list(tmp_path.glob("*.f32"))


def test_embedding_service_degraded_without_model():
    service = EmbeddingService("missing-model")

    result = asyncio.run(service.upsert_text(
        rust=FakeRust(),
        sqlite_path=Path("knownet.db"),
        tmp_dir=Path("tmp"),
        owner_type="message",
        owner_id="msg_1",
        text="hello",
        updated_at="2026-05-01T00:00:00Z",
    ))

    assert result["stored"] is False
    assert "embedding" in result["reason"].lower()
