import struct

import aiosqlite

from knownet_api.routes.search import _cosine_similarity, _decode_vector, _semantic_results


class FakeEmbedding:
    model_name = "fake-model"

    async def encode(self, q: str):
        return [1.0, 0.0, 0.0]


class FakeState:
    def __init__(self, settings):
        self.settings = settings
        self.embedding_service = FakeEmbedding()


class FakeRequest:
    def __init__(self, settings):
        self.app = type("App", (), {"state": FakeState(settings)})()


class FakeSettings:
    def __init__(self, sqlite_path):
        self.sqlite_path = sqlite_path


def test_vector_decode_and_cosine_similarity():
    blob = struct.pack("<3f", 1.0, 0.0, 0.0)
    assert _decode_vector(blob, 3) == [1.0, 0.0, 0.0]
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0


async def _seed_semantic_db(sqlite_path):
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute(
            "CREATE TABLE embeddings (id TEXT, owner_type TEXT, owner_id TEXT, vector BLOB, dims INTEGER, model TEXT)"
        )
        await connection.execute("CREATE TABLE pages (id TEXT, slug TEXT, title TEXT, path TEXT)")
        await connection.execute(
            "INSERT INTO pages (id, slug, title, path) VALUES ('page_neat', 'neat', 'NEAT', 'data/pages/neat.md')"
        )
        await connection.execute(
            "INSERT INTO embeddings (id, owner_type, owner_id, vector, dims, model) VALUES (?, ?, ?, ?, ?, ?)",
            ("emb_1", "page", "page_neat", struct.pack("<3f", 1.0, 0.0, 0.0), 3, "fake-model"),
        )
        await connection.execute(
            "INSERT INTO embeddings (id, owner_type, owner_id, vector, dims, model) VALUES (?, ?, ?, ?, ?, ?)",
            ("emb_2", "message", "msg_1", struct.pack("<3f", 0.0, 1.0, 0.0), 3, "fake-model"),
        )
        await connection.commit()


def test_semantic_results_rank_page(tmp_path):
    import asyncio

    sqlite_path = tmp_path / "knownet.db"
    asyncio.run(_seed_semantic_db(sqlite_path))

    results = asyncio.run(_semantic_results("neat", FakeRequest(FakeSettings(sqlite_path))))

    assert results[0]["slug"] == "neat"
    assert results[0]["match_type"] == "semantic"
    assert results[0]["score"] == 1.0
