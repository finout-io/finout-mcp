"""
Filter Cache - manages caching of filter metadata and values.

Implements a two-tier caching strategy:
1. Metadata Cache (15-min TTL): Stores filter keys, types, paths, cost centers WITHOUT values
2. Value Cache (10-min TTL): Stores values for individual filters as requested

This prevents the 10MB filter problem by lazy-loading values only when needed.
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .finout_client import FinoutClient


class FilterCache:
    """
    Two-tier cache for Finout filter data.

    Tier 1: Metadata (filters structure without values) - 15 min TTL
    Tier 2: Values (specific filter values) - 10 min TTL per filter
    """

    def __init__(self, client: "FinoutClient"):
        """
        Initialize filter cache.

        Args:
            client: FinoutClient instance for fetching data
        """
        self.client = client

        # Metadata cache (all filters without values)
        self._metadata_cache: dict[str, Any] | None = None
        self._metadata_cache_time: datetime | None = None
        self._metadata_ttl = timedelta(minutes=15)

        # Value cache (individual filter values)
        # Key format: "{cost_center}:{type}:{filter_key}"
        self._value_cache: dict[str, dict[str, Any]] = {}
        self._value_cache_times: dict[str, datetime] = {}
        self._value_ttl = timedelta(minutes=10)

        # Lock for thread-safe cache updates
        self._metadata_lock = asyncio.Lock()
        self._value_locks: dict[str, asyncio.Lock] = {}

    def _make_cache_key(
        self, filter_key: str, cost_center: str | None = None, filter_type: str | None = None
    ) -> str:
        """
        Create cache key for a specific filter.

        Args:
            filter_key: Filter key (e.g., "service", "region")
            cost_center: Cost center (e.g., "aws", "gcp")
            filter_type: Filter type (e.g., "filter", "tag")

        Returns:
            Cache key string
        """
        parts = []
        if cost_center:
            parts.append(cost_center)
        if filter_type:
            parts.append(filter_type)
        parts.append(filter_key)
        return ":".join(parts)

    async def get_metadata(
        self, date: dict[str, int] | None = None, use_cache: bool = True
    ) -> dict[str, Any]:
        """
        Get filter metadata (without values).

        Args:
            date: Date range for filter query
            use_cache: Whether to use cached metadata

        Returns:
            Filter metadata organized by cost center
        """
        # Check cache
        if use_cache and self._metadata_cache:
            if self._metadata_cache_time:
                age = datetime.now() - self._metadata_cache_time
                if age < self._metadata_ttl:
                    return self._metadata_cache

        # Fetch fresh data (with lock to prevent duplicate requests)
        async with self._metadata_lock:
            # Double-check after acquiring lock
            if use_cache and self._metadata_cache:
                if self._metadata_cache_time:
                    age = datetime.now() - self._metadata_cache_time
                    if age < self._metadata_ttl:
                        return self._metadata_cache

            # Fetch from API (without values)
            metadata = await self.client._fetch_filters_metadata(date)

            # Update cache
            self._metadata_cache = metadata
            self._metadata_cache_time = datetime.now()

            return metadata

    async def get_filter_values(
        self,
        filter_key: str,
        cost_center: str | None = None,
        filter_type: str | None = None,
        date: dict[str, int] | None = None,
        limit: int = 100,
        use_cache: bool = True,
    ) -> list[Any]:
        """
        Get values for a specific filter (lazy-loaded).

        Args:
            filter_key: Filter key to fetch values for
            cost_center: Cost center filter belongs to
            filter_type: Type of filter
            date: Date range for value query
            limit: Maximum number of values to return
            use_cache: Whether to use cached values

        Returns:
            List of filter values (truncated to limit)
        """
        cache_key = self._make_cache_key(filter_key, cost_center, filter_type)

        # Check cache
        if use_cache and cache_key in self._value_cache:
            cache_time = self._value_cache_times.get(cache_key)
            if cache_time:
                age = datetime.now() - cache_time
                if age < self._value_ttl:
                    cached_values = self._value_cache[cache_key].get("values", [])
                    return cached_values[:limit]

        # Get or create lock for this filter
        if cache_key not in self._value_locks:
            self._value_locks[cache_key] = asyncio.Lock()

        # Fetch fresh data (with lock to prevent duplicate requests)
        async with self._value_locks[cache_key]:
            # Double-check after acquiring lock
            if use_cache and cache_key in self._value_cache:
                cache_time = self._value_cache_times.get(cache_key)
                if cache_time:
                    age = datetime.now() - cache_time
                    if age < self._value_ttl:
                        cached_values = self._value_cache[cache_key].get("values", [])
                        return cached_values[:limit]

            # Fetch from API
            values = await self.client._fetch_filter_values(
                filter_key, cost_center, filter_type, date
            )

            # Update cache
            self._value_cache[cache_key] = {
                "filter_key": filter_key,
                "cost_center": cost_center,
                "filter_type": filter_type,
                "values": values,
                "total_count": len(values),
            }
            self._value_cache_times[cache_key] = datetime.now()

            return values[:limit]

    def clear_metadata_cache(self):
        """Clear the metadata cache."""
        self._metadata_cache = None
        self._metadata_cache_time = None

    def clear_value_cache(self, filter_key: str | None = None):
        """
        Clear value cache.

        Args:
            filter_key: Specific filter to clear, or None to clear all
        """
        if filter_key:
            # Clear specific filter
            keys_to_remove = [
                k
                for k in self._value_cache.keys()
                if k.endswith(f":{filter_key}") or k == filter_key
            ]
            for key in keys_to_remove:
                del self._value_cache[key]
                if key in self._value_cache_times:
                    del self._value_cache_times[key]
        else:
            # Clear all
            self._value_cache.clear()
            self._value_cache_times.clear()

    def clear_all(self):
        """Clear all caches."""
        self.clear_metadata_cache()
        self.clear_value_cache()

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        now = datetime.now()

        metadata_age = None
        if self._metadata_cache_time:
            metadata_age = (now - self._metadata_cache_time).total_seconds()

        value_cache_entries = []
        for cache_key, cache_time in self._value_cache_times.items():
            age = (now - cache_time).total_seconds()
            value_cache_entries.append(
                {
                    "key": cache_key,
                    "age_seconds": age,
                    "is_fresh": age < self._value_ttl.total_seconds(),
                }
            )

        return {
            "metadata": {
                "cached": self._metadata_cache is not None,
                "age_seconds": metadata_age,
                "is_fresh": (
                    metadata_age < self._metadata_ttl.total_seconds()
                    if metadata_age is not None
                    else False
                ),
            },
            "values": {"count": len(self._value_cache), "entries": value_cache_entries},
        }
