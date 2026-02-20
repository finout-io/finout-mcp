"""
Tests for Internal API integration - filter discovery and cost queries.
"""

from unittest.mock import Mock, patch

import httpx
import pytest

from src.finout_mcp_server.finout_client import FinoutClient


@pytest.fixture
def mock_internal_response():
    """Mock response from internal API"""
    mock = Mock()
    mock.status_code = 200
    mock.json.return_value = {"test": "data"}
    mock.raise_for_status = Mock()
    return mock


@pytest.fixture
def sample_filters():
    """Sample filters response"""
    return {
        "aws": {
            "filter": [
                {"key": "service", "path": "aws.service", "values": ["ec2", "s3", "rds"]},
                {"key": "region", "path": "aws.region", "values": ["us-east-1", "us-west-2"]},
                {"key": "account", "path": "aws.account", "values": ["123456789"]},
            ],
            "tag": [
                {"key": "environment", "path": "aws.tag.environment", "values": ["prod", "staging"]}
            ],
        },
        "gcp": {
            "filter": [
                {"key": "service", "path": "gcp.service", "values": ["compute", "storage"]},
                {"key": "project", "path": "gcp.project", "values": ["my-project"]},
            ]
        },
        "k8s": {
            "filter": [
                {"key": "pod_name", "path": "k8s.pod_name", "values": ["api-server", "worker"]},
                {"key": "namespace", "path": "k8s.namespace", "values": ["default", "production"]},
            ]
        },
    }


@pytest.fixture
def sample_cost_response():
    """Sample cost query response"""
    return {
        "total": 15420.50,
        "breakdown": [
            {"name": "ec2", "cost": 8500.00},
            {"name": "s3", "cost": 3200.25},
            {"name": "rds", "cost": 2500.00},
            {"name": "lambda", "cost": 1220.25},
        ],
        "currency": "USD",
    }


class TestFinoutClientInternalAPI:
    """Tests for FinoutClient internal API methods"""

    @pytest.mark.asyncio
    async def test_filter_cache_property(self):
        """Test filter_cache property initialization"""
        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account-123",
        )

        # Should lazy-initialize
        cache1 = client.filter_cache
        cache2 = client.filter_cache

        # Should return same instance
        assert cache1 is cache2

        await client.close()

    @pytest.mark.asyncio
    async def test_filter_cache_property_without_url(self):
        """Test filter_cache property raises error without internal URL"""
        with patch.dict("os.environ", {}, clear=True):
            client = FinoutClient(
                client_id="test", secret_key="test", allow_missing_credentials=False
            )
            client.internal_api_url = None
            client.internal_client = None

            with pytest.raises(ValueError, match="Internal API URL not configured"):
                _ = client.filter_cache

            await client.close()

    def test_current_date_range(self):
        """Test _current_date_range generates valid date range"""
        client = FinoutClient(client_id="test", secret_key="test", allow_missing_credentials=False)

        date_range = client._current_date_range()

        # New format uses relativeRange
        assert "relativeRange" in date_range or "from" in date_range
        assert "type" in date_range

    @pytest.mark.asyncio
    async def test_fetch_filters_metadata(self, mock_internal_response, sample_filters):
        """Test fetching filter metadata without values"""
        mock_internal_response.json.return_value = sample_filters

        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account-123",
        )

        with patch.object(
            client.internal_client, "post", return_value=mock_internal_response
        ) as mock_post:
            result = await client._fetch_filters_metadata()

            # Verify API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "/cost-service/filters"
            assert call_args[1]["json"]["includeValues"] is False

            # Verify result - values should be stripped
            assert "aws" in result
            assert "filter" in result["aws"]
            # Check that values are not included (metadata only)
            for filter_item in result["aws"]["filter"]:
                assert "values" not in filter_item or filter_item.get("values") == []

        await client.close()

    @pytest.mark.asyncio
    async def test_fetch_filter_values(self, mock_internal_response):
        """Test fetching values for a specific filter"""
        # API returns list format with costCenter
        mock_response = [
            {
                "costCenter": "aws",
                "key": "service",
                "type": "col",
                "path": "aws.service",
                "values": {"ec2": 1, "s3": 1, "rds": 1},  # Values dict format
            }
        ]
        mock_internal_response.json.return_value = mock_response

        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account-123",
        )

        with patch.object(
            client.internal_client, "post", return_value=mock_internal_response
        ) as mock_post:
            result = await client._fetch_filter_values("service", "aws", "col")

            # Verify API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]["json"]["includeValues"] is True
            assert call_args[1]["json"]["filterKey"] == "service"

            # Verify result - should extract keys from values dict
            assert set(result) == {"ec2", "s3", "rds"}

        await client.close()

    @pytest.mark.asyncio
    async def test_get_filters_metadata_uses_cache(self, mock_internal_response, sample_filters):
        """Test get_filters_metadata uses cache"""
        mock_internal_response.json.return_value = sample_filters

        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account-123",
        )

        with patch.object(
            client.internal_client, "post", return_value=mock_internal_response
        ) as mock_post:
            # First call
            result1 = await client.get_filters_metadata()

            # Second call - should use cache
            result2 = await client.get_filters_metadata()

            # Should only make one API call
            assert mock_post.call_count == 1
            # Results should be same (values stripped from both)
            assert result1 == result2

        await client.close()

    @pytest.mark.asyncio
    async def test_search_filters(self, mock_internal_response, sample_filters):
        """Test searching filters by keyword"""
        mock_internal_response.json.return_value = sample_filters

        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account-123",
        )

        with patch.object(client.internal_client, "post", return_value=mock_internal_response):
            # Search for "pod"
            results = await client.search_filters("pod")

            # Should find pod_name filter
            assert len(results) > 0
            assert any("pod" in r["key"].lower() for r in results)

            # Search for "service" in aws
            results_aws = await client.search_filters("service", cost_center="aws")
            assert len(results_aws) > 0
            assert all(r["costCenter"] == "aws" for r in results_aws)  # Use costCenter (camelCase)

        await client.close()

    def test_build_filter_payload(self):
        """Test building filter payload for API"""
        client = FinoutClient(client_id="test", secret_key="test", allow_missing_credentials=False)

        # Filters must include costCenter, key, path, type (from search_filters)
        filters = [
            {
                "costCenter": "amazon-cur",
                "key": "service",
                "path": "AWS/Services",
                "type": "col",
                "value": "ec2",
                "operator": "is",
            }
        ]

        result = client._build_filter_payload(filters)

        # Single filter: return as-is
        assert result["costCenter"] == "amazon-cur"
        assert result["key"] == "service"
        assert result["operator"] == "is"
        assert result["value"] == "ec2"

    def test_build_filter_payload_validation(self):
        """Test filter payload validation"""
        client = FinoutClient(client_id="test", secret_key="test", allow_missing_credentials=False)

        # Missing costCenter
        with pytest.raises(ValueError, match="missing required field 'costCenter'"):
            client._build_filter_payload(
                [{"key": "service", "path": "AWS/Services", "type": "col", "value": "ec2"}]
            )

        # Missing value
        with pytest.raises(ValueError, match="missing required field 'value'"):
            client._build_filter_payload(
                [
                    {
                        "costCenter": "amazon-cur",
                        "key": "service",
                        "path": "AWS/Services",
                        "type": "col",
                    }
                ]
            )

        # Not a dict
        with pytest.raises(ValueError, match="must be a dictionary"):
            client._build_filter_payload(["invalid"])

    @pytest.mark.asyncio
    async def test_query_costs_with_filters(self, mock_internal_response, sample_cost_response):
        """Test querying costs with filters"""
        mock_internal_response.json.return_value = sample_cost_response

        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account-123",
        )

        with patch.object(
            client.internal_client, "post", return_value=mock_internal_response
        ) as mock_post:
            result = await client.query_costs_with_filters(
                time_period="last_30_days",
                filters=[
                    {
                        "costCenter": "amazon-cur",
                        "key": "service",
                        "path": "AWS/Services",
                        "type": "col",
                        "value": "ec2",
                        "operator": "is",
                    }
                ],
                group_by=[
                    {
                        "costCenter": "amazon-cur",
                        "key": "service",
                        "path": "AWS/Services",
                        "type": "col",
                    }
                ],
                x_axis_group_by="daily",
            )

            # Verify API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "/cost-service/cost"

            payload = call_args[1]["json"]
            assert "date" in payload
            assert "filters" in payload
            assert "groupBys" in payload
            assert payload["xAxisGroupBy"] == "daily"

            # Verify result
            assert result == sample_cost_response

        await client.close()

    @pytest.mark.asyncio
    async def test_query_costs_without_internal_api(self):
        """Test query_costs_with_filters raises error without internal API"""
        with patch.dict("os.environ", {}, clear=True):
            client = FinoutClient(
                client_id="test", secret_key="test", allow_missing_credentials=False
            )
            client.internal_api_url = None
            client.internal_client = None

            with pytest.raises(ValueError, match="Internal API client not configured"):
                await client.query_costs_with_filters(time_period="last_30_days")

            await client.close()

        await client.close()

    @pytest.mark.asyncio
    async def test_query_costs_auth_error(self):
        """Test query_costs_with_filters handles authentication errors"""
        client = FinoutClient(
            client_id="test", secret_key="test", internal_api_url="http://localhost:3000"
        )

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Auth failed", request=Mock(), response=mock_response
        )

        with patch.object(client.internal_client, "post", return_value=mock_response):
            with pytest.raises(ValueError, match="Authentication failed"):
                await client.query_costs_with_filters(time_period="last_30_days")

        await client.close()

    @pytest.mark.asyncio
    async def test_query_costs_forbidden_error(self):
        """Test query_costs_with_filters handles permission errors"""
        client = FinoutClient(
            client_id="test", secret_key="test", internal_api_url="http://localhost:3000"
        )

        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=Mock(), response=mock_response
        )

        with patch.object(client.internal_client, "post", return_value=mock_response):
            with pytest.raises(ValueError, match="Access denied"):
                await client.query_costs_with_filters(time_period="last_30_days")

        await client.close()

    @pytest.mark.asyncio
    async def test_query_costs_timeout_error(self):
        """Test query_costs_with_filters handles timeout errors"""
        client = FinoutClient(
            client_id="test", secret_key="test", internal_api_url="http://localhost:3000"
        )

        with patch.object(
            client.internal_client, "post", side_effect=httpx.TimeoutException("Timeout")
        ):
            with pytest.raises(ValueError, match="timed out"):
                await client.query_costs_with_filters(time_period="last_30_days")

        await client.close()

    @pytest.mark.asyncio
    async def test_query_costs_validation(self):
        """Test query_costs_with_filters validates parameters"""
        client = FinoutClient(
            client_id="test", secret_key="test", internal_api_url="http://localhost:3000"
        )

        # Invalid group_by (not a list)
        with pytest.raises(ValueError, match="group_by must be a list"):
            await client.query_costs_with_filters(
                time_period="last_30_days",
                group_by="service",  # Should be a list
            )

        # Invalid x_axis_group_by
        with pytest.raises(ValueError, match="x_axis_group_by must be"):
            await client.query_costs_with_filters(
                time_period="last_30_days",
                x_axis_group_by="yearly",  # Invalid value
            )

        await client.close()

    def test_normalize_cost_center(self):
        """Test cost center normalization handles various capitalizations"""
        client = FinoutClient(
            client_id="test", secret_key="test", internal_api_url="http://localhost:3000"
        )

        # Test virtualTag normalization (the problematic case)
        assert client._normalize_cost_center("VIRTUALTAG") == "virtualTag"
        assert client._normalize_cost_center("virtualtag") == "virtualTag"
        assert client._normalize_cost_center("VirtualTag") == "virtualTag"
        assert client._normalize_cost_center("virtualTag") == "virtualTag"

        # Test other known cost centers
        assert client._normalize_cost_center("AMAZON-CUR") == "amazon-cur"
        assert client._normalize_cost_center("Amazon-Cur") == "amazon-cur"
        assert client._normalize_cost_center("KUBERNETES") == "kubernetes"
        assert client._normalize_cost_center("Kubernetes") == "kubernetes"
        assert client._normalize_cost_center("GCP") == "gcp"
        assert client._normalize_cost_center("gcp") == "gcp"

        # Test unknown cost centers (pass through as-is)
        assert client._normalize_cost_center("unknown-center") == "unknown-center"
        assert client._normalize_cost_center("CustomCenter") == "CustomCenter"

    @pytest.mark.asyncio
    async def test_get_account_context(self, mock_internal_response, sample_filters):
        """Test get_account_context returns expected structure"""
        mock_internal_response.json.return_value = sample_filters

        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account-123",
        )

        # Pre-populate account info to avoid extra API call
        client._account_info = {
            "name": "Test Account",
            "payerId": "payer-123",
            "featureFlags": {"mcp_enabled": True},
        }

        with patch.object(client.internal_client, "post", return_value=mock_internal_response):
            result = await client.get_account_context()

            assert result["account_name"] == "Test Account"
            assert result["account_id"] == "test-account-123"
            assert "cost_centers" in result
            assert "feature_flags" in result
            assert result["feature_flags"]["mcp_enabled"] is True
            # Verify cost_centers have filter_count
            for cc_info in result["cost_centers"].values():
                assert "filter_count" in cc_info

        await client.close()

    @pytest.mark.asyncio
    async def test_get_account_context_without_account_info(self):
        """Test get_account_context without internal API returns minimal info"""
        with patch.dict("os.environ", {}, clear=True):
            client = FinoutClient(
                client_id="test", secret_key="test", allow_missing_credentials=False
            )

            result = await client.get_account_context()

            assert result["account_name"] == "Unknown"
            assert result["cost_centers"] == {}

            await client.close()


class TestDebugCurl:
    """Tests for debug curl capture"""

    def test_request_to_curl_post(self):
        """Test POST request generates correct curl with masked secrets"""
        request = httpx.Request(
            "POST",
            "http://internal-api:3000/cost-service/cost",
            headers={
                "Content-Type": "application/json",
                "x-finout-client-id": "real-id",
                "x-finout-secret-key": "real-secret",
                "authorized-account-id": "acct-123",
            },
            json={"date": {"relativeRange": "last30Days"}},
        )

        curl = FinoutClient._request_to_curl(request)

        assert "curl -X POST" in curl
        assert "x-finout-client-id: ***" in curl
        assert "x-finout-secret-key: ***" in curl
        assert "real-id" not in curl
        assert "real-secret" not in curl
        assert "authorized-account-id: acct-123" in curl
        assert "-d '" in curl
        assert "last30Days" in curl
        assert "http://internal-api:3000/cost-service/cost" in curl

    def test_request_to_curl_get(self):
        """Test GET request produces correct curl without -d"""
        request = httpx.Request(
            "GET",
            "http://internal-api:3000/account-service/account/123",
            headers={"Content-Type": "application/json"},
        )

        curl = FinoutClient._request_to_curl(request)

        assert "curl -X GET" in curl
        assert "-d " not in curl
        assert "account-service/account/123" in curl

    @pytest.mark.asyncio
    async def test_collect_curls_returns_and_clears(self):
        """Test collect_curls returns captured curls and clears the list"""
        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account",
        )

        # Simulate captured curls
        client._recent_curls = ["curl -X POST ...", "curl -X GET ..."]

        curls = client.collect_curls()
        assert len(curls) == 2
        assert curls[0] == "curl -X POST ..."

        # Should be cleared
        assert client._recent_curls == []
        assert client.collect_curls() == []

        await client.close()


class TestSubmitFeedback:
    """Tests for submit_feedback tool handler"""

    @pytest.mark.asyncio
    async def test_submit_feedback_valid(self):
        """Test submit_feedback accepts valid input"""
        from src.finout_mcp_server.server import feedback_log, submit_feedback_impl

        initial_count = len(feedback_log)

        result = await submit_feedback_impl(
            {
                "rating": 4,
                "query_type": "cost_query",
                "tools_used": ["search_filters", "query_costs"],
                "friction_points": ["slow API"],
                "suggestion": "Cache filter results",
            }
        )

        assert result["status"] == "recorded"
        assert result["total_feedback_count"] == initial_count + 1
        assert feedback_log[-1]["rating"] == 4
        assert feedback_log[-1]["query_type"] == "cost_query"

    @pytest.mark.asyncio
    async def test_submit_feedback_invalid_rating(self):
        """Test submit_feedback rejects invalid rating"""
        from src.finout_mcp_server.server import submit_feedback_impl

        with pytest.raises(ValueError, match="rating must be an integer"):
            await submit_feedback_impl({"rating": 6, "query_type": "cost_query", "tools_used": []})

    @pytest.mark.asyncio
    async def test_submit_feedback_invalid_query_type(self):
        """Test submit_feedback rejects invalid query_type"""
        from src.finout_mcp_server.server import submit_feedback_impl

        with pytest.raises(ValueError, match="query_type must be one of"):
            await submit_feedback_impl(
                {"rating": 3, "query_type": "invalid_type", "tools_used": []}
            )


class TestToolDescriptions:
    """Tests that tool descriptions contain coaching keywords"""

    @pytest.mark.asyncio
    async def test_descriptions_contain_coaching(self):
        """Verify tool descriptions include when-to-use coaching"""
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        server_module.runtime_mode = server_module.MCPMode.PUBLIC.value
        public_tools = await server_module.list_tools()
        tool_map = {t.name: t.description for t in public_tools}

        # query_costs should coach on workflow
        assert "WHEN TO USE" in tool_map["query_costs"]
        assert "search_filters" in tool_map["query_costs"]

        # compare_costs should mention trigger words
        assert "compare" in tool_map["compare_costs"].lower()
        assert "trend" in tool_map["compare_costs"].lower()

        # search_filters should emphasize it's the first step
        assert "FIRST STEP" in tool_map["search_filters"]

        # get_filter_values should reference chaining
        assert "CHAIN" in tool_map["get_filter_values"]

        # get_waste_recommendations should mention trigger words
        assert "savings" in tool_map["get_waste_recommendations"].lower()
        assert "waste" in tool_map["get_waste_recommendations"].lower()

        # list_available_filters should warn against casual use
        assert "ONLY" in tool_map["list_available_filters"]

        # get_usage_unit_types should mention chaining
        assert "CHAIN" in tool_map["get_usage_unit_types"]

        server_module.runtime_mode = server_module.MCPMode.VECTIQOR_INTERNAL.value
        internal_tools = await server_module.list_tools()
        internal_tool_map = {t.name: t.description for t in internal_tools}

        # discover_context should mention named concepts
        assert "named concept" in internal_tool_map["discover_context"].lower()

        # debug_filters should discourage normal use
        assert "DO NOT" in internal_tool_map["debug_filters"]

    @pytest.mark.asyncio
    async def test_new_tools_registered(self):
        """Verify mode-specific tool registration"""
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        server_module.runtime_mode = server_module.MCPMode.PUBLIC.value
        public_tools = await server_module.list_tools()
        public_tool_names = {t.name for t in public_tools}
        assert "get_account_context" not in public_tool_names
        assert "submit_feedback" not in public_tool_names
        assert "get_anomalies" in public_tool_names
        assert len(public_tools) == 9

        server_module.runtime_mode = server_module.MCPMode.VECTIQOR_INTERNAL.value
        internal_tools = await server_module.list_tools()
        internal_tool_names = {t.name for t in internal_tools}
        assert "get_account_context" in internal_tool_names
        assert "submit_feedback" in internal_tool_names
        assert "get_waste_recommendations" in internal_tool_names
        assert len(internal_tools) == 13
