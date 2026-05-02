import asyncio
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .rust_core import RustCoreClient


@dataclass
class EmbeddingStatus:
    status: str
    model: str
    reason: str | None = None
    dims: int | None = None


class EmbeddingModel(Protocol):
    def encode(self, text: str, normalize_embeddings: bool = True) -> Any:
        ...


class EmbeddingUnavailable(RuntimeError):
    pass


class EmbeddingService:
    def __init__(self, model_name: str, model: EmbeddingModel | None = None) -> None:
        self.model_name = model_name
        self.model: EmbeddingModel | None = model
        self.dims: int | None = None
        self.status = EmbeddingStatus(
            status="ready" if model else "unavailable",
            model=model_name,
            reason=None if model else "Local embedding model is not loaded.",
        )

    async def load(self, *, allow_download: bool = False) -> dict[str, str | int | None]:
        if self.model:
            return self.health()
        self.status = EmbeddingStatus(status="loading", model=self.model_name, reason=None)
        try:
            model = await asyncio.to_thread(self._load_model_sync, allow_download)
            self.model = model
            probe = await self.encode("embedding readiness probe")
            self.dims = len(probe)
            self.status = EmbeddingStatus(status="ready", model=self.model_name, dims=self.dims)
        except Exception as error:
            self.model = None
            self.dims = None
            self.status = EmbeddingStatus(
                status="unavailable",
                model=self.model_name,
                reason=f"embedding_model_unavailable: {error}",
            )
        return self.health()

    def _load_model_sync(self, allow_download: bool) -> EmbeddingModel:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise EmbeddingUnavailable("sentence-transformers is not installed") from error

        if allow_download:
            return SentenceTransformer(self.model_name)
        try:
            return SentenceTransformer(self.model_name, local_files_only=True)
        except TypeError as error:
            raise EmbeddingUnavailable("installed sentence-transformers does not support local_files_only") from error

    def health(self) -> dict[str, str | int | None]:
        return {
            "status": self.status.status,
            "model": self.status.model,
            "reason": self.status.reason,
            "dims": self.status.dims,
        }

    def prefetch_plan(self) -> dict[str, str]:
        return {
            "model": self.model_name,
            "command": "POST /api/maintenance/embedding/load?allow_download=true",
            "status": "planned",
        }

    async def encode(self, text: str) -> list[float]:
        if not self.model:
            raise EmbeddingUnavailable("embedding_model_unavailable")
        try:
            vector = await asyncio.to_thread(self._encode_sync, text)
        except Exception as error:
            self.status = EmbeddingStatus(
                status="unavailable",
                model=self.model_name,
                reason=f"embedding_encode_failed: {error}",
                dims=self.dims,
            )
            raise
        if self.dims is None:
            self.dims = len(vector)
            self.status = EmbeddingStatus(status="ready", model=self.model_name, dims=self.dims)
        return vector

    def _encode_sync(self, text: str) -> list[float]:
        assert self.model is not None
        encoded = self.model.encode(text, normalize_embeddings=True)
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        return [float(value) for value in encoded]

    async def upsert_text(
        self,
        *,
        rust: RustCoreClient,
        sqlite_path: Path,
        tmp_dir: Path,
        owner_type: str,
        owner_id: str,
        text: str,
        updated_at: str,
    ) -> dict[str, Any]:
        if not text.strip():
            return {"stored": False, "reason": "empty_text"}
        if not self.model:
            return {"stored": False, "reason": self.status.reason or "embedding_model_unavailable"}

        try:
            vector = await self.encode(text)
        except Exception as error:
            return {"stored": False, "reason": f"embedding_encode_failed: {error}"}

        tmp_dir.mkdir(parents=True, exist_ok=True)
        embedding_id = self._embedding_id(owner_type, owner_id)
        vector_path = tmp_dir / f"{embedding_id}.f32"
        vector_path.write_bytes(struct.pack(f"<{len(vector)}f", *vector))
        try:
            result = await rust.request(
                "embedding_upsert",
                {
                    "sqlite_path": str(sqlite_path),
                    "embedding_id": embedding_id,
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "model": self.model_name,
                    "vector_path": str(vector_path),
                    "dims": len(vector),
                    "updated_at": updated_at,
                },
            )
        except Exception as error:
            return {"stored": False, "reason": f"embedding_upsert_failed: {error}"}
        finally:
            if vector_path.exists():
                vector_path.unlink()
        return {"stored": True, **result, "dims": len(vector)}

    def _embedding_id(self, owner_type: str, owner_id: str) -> str:
        digest = hashlib.sha1(f"{owner_type}:{owner_id}:{self.model_name}".encode("utf-8")).hexdigest()[:16]
        return f"emb_{digest}"
