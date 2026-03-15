import time
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request

from redis_client import client

_lua_dir = Path(__file__).parent / "lua"


class RateLimiter:
    def __init__(self) -> None:
        self._fixed_window_script = client.register_script(
            (_lua_dir / "fixed_window.lua").read_text()
        )
        self._sliding_window_script = client.register_script(
            (_lua_dir / "sliding_window.lua").read_text()
        )
        self._sliding_log_script = client.register_script(
            (_lua_dir / "sliding_log.lua").read_text()
        )

    def fixed_window(self, limit: int, window: int) -> Any:
        # 每個 window 用獨立的 key（包含 window 編號）
        # 這會造成 boundary 漏洞：cross-window 可發送 2x 請求
        async def dependency(request: Request) -> None:
            assert request.client is not None
            window_id = int(time.time()) // window
            key = f"IP:{request.client.host}:fixed:{window_id}"
            result = await self._fixed_window_script(keys=[key], args=[limit, window])
            if result != 0:
                raise HTTPException(status_code=429, detail="Too Many Requests")

        return Depends(dependency)

    def sliding_window(self, limit: int, window: int) -> Any:
        # sliding_window.lua: now=ms, windowSize=ms, threshold=limit
        # 回傳 0 表示允許，否則回傳 "ec prev curr" 字串
        async def dependency(request: Request) -> None:
            assert request.client is not None
            key = f"IP:{request.client.host}:sw"
            now = int(time.time() * 1000)
            result = await self._sliding_window_script(
                keys=[key], args=[now, window * 1000, limit]
            )
            if result != 0:
                raise HTTPException(status_code=429, detail="Too Many Requests")

        return Depends(dependency)

    def sliding_log(self, limit: int, window: int) -> Any:
        # sliding_logs.lua: now=sec, window=sec, limit, unique=ns timestamp
        # 回傳 limit - amount，負數表示已達上限（修正 off-by-one 後 0 也是達上限）
        async def dependency(request: Request) -> None:
            assert request.client is not None
            key = f"IP:{request.client.host}:sl"
            now = int(time.time())
            unique = time.time_ns()
            remaining = await self._sliding_log_script(
                keys=[key], args=[now, window, limit, unique]
            )
            if int(remaining) <= 0:
                raise HTTPException(status_code=429, detail="Too Many Requests")

        return Depends(dependency)

    def __call__(
        self,
        algorithm: Literal["fixed_window", "sliding_window", "sliding_log"],
        limit: int,
        window: int,
    ) -> Any:
        if algorithm == "fixed_window":
            return self.fixed_window(limit=limit, window=window)
        elif algorithm == "sliding_window":
            return self.sliding_window(limit=limit, window=window)
        else:
            return self.sliding_log(limit=limit, window=window)


rate_limiter = RateLimiter()
