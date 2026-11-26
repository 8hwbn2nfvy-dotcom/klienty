"""Не чаще одного запроса в секунду на один адрес (сервис или домен)."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class PerKeyLimiter:
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._loop: asyncio.AbstractEventLoop | None = None
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last: dict[str, float] = {}

    async def wait(self, key: str) -> None:
        loop = asyncio.get_running_loop()
        if loop is not self._loop:  # замки привязаны к циклу событий; новый цикл — новые замки
            self._loop, self._locks = loop, defaultdict(asyncio.Lock)
        async with self._locks[key]:
            delay = self._last.get(key, 0.0) + self.interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[key] = time.monotonic()


limiter = PerKeyLimiter(1.0)
