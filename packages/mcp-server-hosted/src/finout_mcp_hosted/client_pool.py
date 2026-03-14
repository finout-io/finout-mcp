"""LRU client pool for hosted multi-user MCP server.

Pools FinoutClient instances by (account_id, auth_mode, api_url) so concurrent
requests sharing the same identity reuse one client (and its FilterCache).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from finout_mcp_server.finout_client import FinoutClient


class ClientPool:
    """Thread/task-safe LRU pool of FinoutClient instances."""

    def __init__(self, max_size: int = 50, ttl: float = 3600.0) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._lock = asyncio.Lock()
        # key → (client, last_access_time, kwargs used to create it)
        self._pool: dict[tuple[str, ...], tuple[FinoutClient, float, dict[str, Any]]] = {}

    async def get_or_create(
        self,
        fingerprint: tuple[str, ...],
        **client_kwargs: Any,
    ) -> FinoutClient:
        """Return an existing client or create a new one.

        The lock is held only for the dict lookup/insert — microseconds, not
        during request processing.
        """
        now = time.monotonic()

        async with self._lock:
            entry = self._pool.get(fingerprint)
            if entry is not None:
                client, _last, kwargs = entry
                # Check if the client's HTTP connections are still open
                public_ok = not getattr(getattr(client, "client", None), "is_closed", False)
                internal_ok = not getattr(
                    getattr(client, "internal_client", None), "is_closed", False
                )
                if public_ok and internal_ok:
                    self._pool[fingerprint] = (client, now, kwargs)
                    return client
                # Stale — will recreate below

            # Evict expired entries
            expired = [
                k for k, (_, ts, _kw) in self._pool.items() if now - ts > self._ttl
            ]
            for k in expired:
                old_client = self._pool.pop(k)[0]
                await self._close_quietly(old_client)

            # Evict LRU if at capacity
            while len(self._pool) >= self._max_size:
                lru_key = min(self._pool, key=lambda k: self._pool[k][1])
                old_client = self._pool.pop(lru_key)[0]
                await self._close_quietly(old_client)

            client = FinoutClient(**client_kwargs)
            self._pool[fingerprint] = (client, now, client_kwargs)
            return client

    async def close_all(self) -> None:
        """Close all pooled clients."""
        async with self._lock:
            for _fp, (client, _ts, _kw) in self._pool.items():
                await self._close_quietly(client)
            self._pool.clear()

    @staticmethod
    async def _close_quietly(client: FinoutClient) -> None:
        try:
            await client.close()
        except Exception:
            pass

    def __len__(self) -> int:
        return len(self._pool)
