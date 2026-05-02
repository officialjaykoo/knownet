import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


class RustCoreError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class RustCoreClient:
    def __init__(self, binary_path: Path, timeout_seconds: float = 10.0) -> None:
        self.binary_path = binary_path
        self.timeout_seconds = timeout_seconds
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.reader_task: asyncio.Task[None] | None = None
        self.available = False

    async def start(self) -> None:
        for _ in range(3):
            try:
                self.process = await asyncio.create_subprocess_exec(
                    str(self.binary_path),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                self.reader_task = asyncio.create_task(self._read_loop())
                await self.request("ping", {})
                self.available = True
                return
            except Exception:
                await self.stop()
                await asyncio.sleep(0.2)
        self.available = False

    async def stop(self) -> None:
        self.available = False
        if self.reader_task:
            self.reader_task.cancel()
            self.reader_task = None
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
        self.process = None

    async def request(self, cmd: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.process or not self.process.stdin:
            raise RustCoreError("daemon_unavailable", "Rust daemon is unavailable")
        request_id = f"req_{uuid4().hex}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[request_id] = future
        payload = json.dumps({"id": request_id, "cmd": cmd, "params": params}, ensure_ascii=False)
        self.process.stdin.write((payload + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        try:
            response = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        finally:
            self.pending.pop(request_id, None)
        if not response.get("ok"):
            error = response.get("error") or {}
            raise RustCoreError(error.get("code", "daemon_error"), error.get("message", "Rust daemon error"), error.get("details"))
        return response.get("result") or {}

    async def _read_loop(self) -> None:
        if not self.process or not self.process.stdout:
            return
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            request_id = message.get("id")
            future = self.pending.get(request_id)
            if future and not future.done():
                future.set_result(message)

