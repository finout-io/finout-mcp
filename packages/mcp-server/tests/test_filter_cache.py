"""
Tests for FilterCache - filter metadata and value caching.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from src.finout_mcp_server.filter_cache import FilterCache
from src.finout_mcp_server.finout_client import FinoutClient


@pytest.fixture
def mock_client():
    """Create a mock FinoutClient for testing"""
    client = Mock(spec=FinoutClient)
    client.internal_api_url = "http://localhost:3000"
    client._fetch_filters_metadata = AsyncMock()
    client._fetch_filter_values = AsyncMock()
    return client


@pytest.fixture
def filter_cache(mock_client):
    """Create a FilterCache instance with mock client"""
    return FilterCache(mock_client)


@pytest.fixture
def sample_metadata():
    """Sample filter metadata response"""
    return {
        "aws": {
            "filter": [
                {"key": "service", "path": "aws.service", "values": []},
                {"key": "region", "path": "aws.region", "values": []},
            ],
            "tag": [{"key": "environment", "path": "aws.tag.environment", "values": []}],
        },
        "gcp": {"filter": [{"key": "service", "path": "gcp.service", "values": []}]},
    }


@pytest.fixture
def sample_values():
    """Sample filter values"""
    return ["ec2", "s3", "rds", "lambda", "dynamodb"]


class TestFilterCache:
    """Tests for FilterCache class"""

    @pytest.mark.asyncio
    async def test_metadata_caching(self, filter_cache, mock_client, sample_metadata):
        """Test that metadata is cached and not refetched within TTL"""
        mock_client._fetch_filters_metadata.return_value = sample_metadata

        # First call - should fetch from API
        result1 = await filter_cache.get_metadata()
        assert result1 == sample_metadata
        assert mock_client._fetch_filters_metadata.call_count == 1

        # Second call - should use cache
        result2 = await filter_cache.get_metadata()
        assert result2 == sample_metadata
        assert mock_client._fetch_filters_metadata.call_count == 1  # No additional call

        # Verify cache is populated
        assert filter_cache._metadata_cache == sample_metadata
        assert filter_cache._metadata_cache_time is not None

    @pytest.mark.asyncio
    async def test_metadata_cache_expiration(self, filter_cache, mock_client, sample_metadata):
        """Test that metadata cache expires after TTL"""
        mock_client._fetch_filters_metadata.return_value = sample_metadata

        # First call
        await filter_cache.get_metadata()

        # Manually expire cache
        filter_cache._metadata_cache_time = datetime.now() - timedelta(minutes=20)

        # Second call - should fetch again
        await filter_cache.get_metadata()
        assert mock_client._fetch_filters_metadata.call_count == 2

    @pytest.mark.asyncio
    async def test_metadata_cache_bypass(self, filter_cache, mock_client, sample_metadata):
        """Test that cache can be bypassed with use_cache=False"""
        mock_client._fetch_filters_metadata.return_value = sample_metadata

        # First call
        await filter_cache.get_metadata()
        assert mock_client._fetch_filters_metadata.call_count == 1

        # Second call with use_cache=False
        await filter_cache.get_metadata(use_cache=False)
        assert mock_client._fetch_filters_metadata.call_count == 2

    @pytest.mark.asyncio
    async def test_value_lazy_loading(self, filter_cache, mock_client, sample_values):
        """Test that values are lazy-loaded and cached"""
        mock_client._fetch_filter_values.return_value = sample_values

        # First call - should fetch from API
        result1 = await filter_cache.get_filter_values("service", "aws", "filter")
        assert result1 == sample_values
        assert mock_client._fetch_filter_values.call_count == 1

        # Second call - should use cache
        result2 = await filter_cache.get_filter_values("service", "aws", "filter")
        assert result2 == sample_values
        assert mock_client._fetch_filter_values.call_count == 1  # No additional call

    @pytest.mark.asyncio
    async def test_value_cache_different_filters(self, filter_cache, mock_client, sample_values):
        """Test that different filters have separate cache entries"""
        mock_client._fetch_filter_values.return_value = sample_values

        # Fetch values for two different filters
        await filter_cache.get_filter_values("service", "aws", "filter")
        await filter_cache.get_filter_values("region", "aws", "filter")

        # Should have made two API calls
        assert mock_client._fetch_filter_values.call_count == 2

        # Both should be cached
        assert len(filter_cache._value_cache) == 2

    @pytest.mark.asyncio
    async def test_value_cache_limit(self, filter_cache, mock_client):
        """Test that value cache respects limit parameter"""
        large_values = [f"value_{i}" for i in range(200)]
        mock_client._fetch_filter_values.return_value = large_values

        # Request with limit
        result = await filter_cache.get_filter_values("service", "aws", "filter", limit=50)

        # Should return only 50 values
        assert len(result) == 50
        assert result == large_values[:50]

    @pytest.mark.asyncio
    async def test_cache_key_generation(self, filter_cache):
        """Test that cache keys are generated correctly"""
        key1 = filter_cache._make_cache_key("service", "aws", "filter")
        assert key1 == "aws:filter:service"

        key2 = filter_cache._make_cache_key("service")
        assert key2 == "service"

        key3 = filter_cache._make_cache_key("service", cost_center="aws")
        assert key3 == "aws:service"

    def test_clear_metadata_cache(self, filter_cache):
        """Test clearing metadata cache"""
        filter_cache._metadata_cache = {"test": "data"}
        filter_cache._metadata_cache_time = datetime.now()

        filter_cache.clear_metadata_cache()

        assert filter_cache._metadata_cache is None
        assert filter_cache._metadata_cache_time is None

    def test_clear_value_cache_specific(self, filter_cache):
        """Test clearing specific filter from value cache"""
        filter_cache._value_cache = {
            "aws:filter:service": {"values": ["ec2"]},
            "aws:filter:region": {"values": ["us-east-1"]},
        }
        filter_cache._value_cache_times = {
            "aws:filter:service": datetime.now(),
            "aws:filter:region": datetime.now(),
        }

        filter_cache.clear_value_cache("service")

        assert "aws:filter:service" not in filter_cache._value_cache
        assert "aws:filter:region" in filter_cache._value_cache

    def test_clear_value_cache_all(self, filter_cache):
        """Test clearing all value cache"""
        filter_cache._value_cache = {
            "aws:filter:service": {"values": ["ec2"]},
            "aws:filter:region": {"values": ["us-east-1"]},
        }
        filter_cache._value_cache_times = {
            "aws:filter:service": datetime.now(),
            "aws:filter:region": datetime.now(),
        }

        filter_cache.clear_value_cache()

        assert len(filter_cache._value_cache) == 0
        assert len(filter_cache._value_cache_times) == 0

    def test_clear_all(self, filter_cache):
        """Test clearing all caches"""
        filter_cache._metadata_cache = {"test": "data"}
        filter_cache._metadata_cache_time = datetime.now()
        filter_cache._value_cache = {"key": {"values": ["val"]}}
        filter_cache._value_cache_times = {"key": datetime.now()}

        filter_cache.clear_all()

        assert filter_cache._metadata_cache is None
        assert filter_cache._metadata_cache_time is None
        assert len(filter_cache._value_cache) == 0
        assert len(filter_cache._value_cache_times) == 0

    def test_cache_stats(self, filter_cache):
        """Test getting cache statistics"""
        # Populate caches
        filter_cache._metadata_cache = {"test": "data"}
        filter_cache._metadata_cache_time = datetime.now() - timedelta(minutes=5)
        filter_cache._value_cache = {
            "aws:filter:service": {"values": ["ec2"]},
            "gcp:filter:service": {"values": ["compute"]},
        }
        filter_cache._value_cache_times = {
            "aws:filter:service": datetime.now() - timedelta(minutes=3),
            "gcp:filter:service": datetime.now() - timedelta(minutes=8),
        }

        stats = filter_cache.get_cache_stats()

        # Check metadata stats
        assert stats["metadata"]["cached"] is True
        assert stats["metadata"]["is_fresh"] is True
        assert stats["metadata"]["age_seconds"] is not None

        # Check value stats
        assert stats["values"]["count"] == 2
        assert len(stats["values"]["entries"]) == 2

    @pytest.mark.asyncio
    async def test_concurrent_access(self, filter_cache, mock_client, sample_metadata):
        """Test that concurrent access to cache is handled correctly"""
        mock_client._fetch_filters_metadata.return_value = sample_metadata

        # Simulate concurrent calls
        tasks = [filter_cache.get_metadata() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All should return same data
        assert all(r == sample_metadata for r in results)

        # Should only have made one API call due to locking
        assert mock_client._fetch_filters_metadata.call_count == 1
