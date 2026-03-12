"""
Tests for Internal API integration - filter discovery and cost queries.
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from finout_mcp_server.server import _auto_granularity
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
    """Sample cost query response (data-explorer flat row format)"""
    return [
        {"Services": "AmazonEC2", "Sum(Amortized Cost)": 8500.00},
        {"Services": "AmazonS3", "Sum(Amortized Cost)": 3200.25},
        {"Services": "AmazonRDS", "Sum(Amortized Cost)": 2500.00},
        {"Services": "AWSLambda", "Sum(Amortized Cost)": 1220.25},
    ]


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
        """Test fetching filter metadata with values for search"""
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
            assert call_args[1]["json"]["includeValues"] is True

            # Verify result structure
            assert "aws" in result
            assert "filter" in result["aws"]
            # Check that value keys are preserved for value-based search
            for filter_item in result["aws"]["filter"]:
                assert "values" in filter_item
                assert len(filter_item["values"]) > 0

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
            assert call_args[0][0] == "/data-explorer-service/preview-data-explorer"

            payload = call_args[1]["json"]
            assert "date" in payload
            assert "filters" in payload
            assert "columns" in payload

            # Verify columns include dateAggregation, dimension, and measurement
            col_types = [c["columnType"] for c in payload["columns"]]
            assert "dateAggregation" in col_types
            assert "dimension" in col_types
            assert "measurement" in col_types

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
            "http://internal-api:3000/data-explorer-service/preview-data-explorer",
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
        assert "http://internal-api:3000/data-explorer-service/preview-data-explorer" in curl

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

    @pytest.mark.asyncio
    async def test_create_dashboard_rolls_back_shell_on_widget_failure(self):
        """If widget creation fails, dashboard shell is cleaned up best-effort."""
        client = FinoutClient(
            client_id="test",
            secret_key="test",
            internal_api_url="http://localhost:3000",
            account_id="test-account",
        )

        create_shell_resp = Mock()
        create_shell_resp.status_code = 200
        create_shell_resp.json.return_value = {"id": "dash-123", "name": "Test"}
        create_shell_resp.raise_for_status = Mock()

        widget_fail_resp = Mock()
        widget_fail_resp.status_code = 500
        widget_fail_resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "http://localhost:3000/dashboard-service/widget"),
                response=httpx.Response(500),
            )
        )

        delete_resp = Mock()
        delete_resp.status_code = 204
        delete_resp.raise_for_status = Mock()

        with (
            patch.object(
                client.internal_client,
                "post",
                new=AsyncMock(side_effect=[create_shell_resp, widget_fail_resp]),
            ) as mock_post,
            patch.object(
                client.internal_client,
                "delete",
                new=AsyncMock(return_value=delete_resp),
            ) as mock_delete,
            patch.object(
                client.internal_client,
                "put",
                new=AsyncMock(),
            ) as mock_put,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.create_dashboard(
                    name="Test",
                    widgets=[{"type": "freeText", "name": "Note", "text": "hello"}],
                )

            assert mock_post.call_count == 2
            mock_delete.assert_awaited_once()
            delete_path = mock_delete.await_args.args[0]
            assert delete_path == "/dashboard-service/dashboard/dash-123"
            mock_put.assert_not_awaited()

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

        server_module.runtime_mode = server_module.MCPMode.BILLY_INTERNAL.value
        internal_tools = await server_module.list_tools()
        internal_tool_map = {t.name: t.description for t in internal_tools}

        # discover_context should mention named concepts
        assert "named concept" in internal_tool_map["discover_context"].lower()

        # debug_filters should discourage normal use
        assert "DO NOT" in internal_tool_map["debug_filters"]
        assert "USER CONSENT" in internal_tool_map["create_dashboard"]
        assert "no markdown" in internal_tool_map["create_dashboard"].lower()
        assert "markdown annotation" not in internal_tool_map["create_dashboard"].lower()

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
        assert len(public_tools) == 18
        assert "get_top_movers" in public_tool_names
        assert "get_unit_economics" in public_tool_names
        assert "get_cost_patterns" in public_tool_names
        assert "get_savings_coverage" in public_tool_names
        assert "get_tag_coverage" in public_tool_names
        assert "get_budget_status" in public_tool_names
        assert "get_cost_statistics" in public_tool_names

        server_module.runtime_mode = server_module.MCPMode.BILLY_INTERNAL.value
        internal_tools = await server_module.list_tools()
        internal_tool_names = {t.name for t in internal_tools}
        assert "get_account_context" in internal_tool_names
        assert "submit_feedback" in internal_tool_names
        assert "get_waste_recommendations" in internal_tool_names
        assert "render_chart" in internal_tool_names
        assert "analyze_virtual_tags" in internal_tool_names
        assert "get_top_movers" in internal_tool_names
        assert "get_unit_economics" in internal_tool_names
        assert "list_data_explorers" in internal_tool_names
        assert len(internal_tools) == 27

    @pytest.mark.asyncio
    async def test_create_dashboard_impl_formats_presentation_hint(self):
        """Dashboard creation hint should not contain unresolved placeholders."""
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            account_id = "acct-1"

            async def create_dashboard(self, name: str, widgets: list[dict]):
                return {"id": "dash-1", "name": name}

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.create_dashboard_impl(
                {
                    "name": "My Dash",
                    "widgets": [{"type": "freeText", "name": "Summary", "text": "hello"}],
                }
            )
        finally:
            server_module.finout_client = original_client

        assert result["url"].endswith("/app/dashboards/dash-1?accountId=acct-1")
        assert "{widget_count}" not in result["_presentation_hint"]
        assert "1 widgets" in result["_presentation_hint"]


class TestAutoGranularity:
    def test_week_periods_return_weekly(self):
        for p in ("this_week", "last_week", "two_weeks_ago"):
            assert _auto_granularity(p) == "weekly"

    def test_last_7_days_returns_daily(self):
        assert _auto_granularity("last_7_days") == "daily"

    def test_month_periods_return_monthly(self):
        for p in ("this_month", "last_month", "month_to_date"):
            assert _auto_granularity(p) == "monthly"

    def test_last_quarter_returns_monthly(self):
        assert _auto_granularity("last_quarter") == "monthly"

    def test_daily_fallbacks(self):
        for p in ("today", "yesterday", "last_30_days"):
            assert _auto_granularity(p) == "daily"

    def test_custom_range_7_days_weekly(self):
        assert _auto_granularity("2026-01-01 to 2026-01-07") == "weekly"

    def test_custom_range_one_month_monthly(self):
        assert _auto_granularity("2026-01-01 to 2026-01-31") == "monthly"

    def test_custom_range_10_days_daily(self):
        assert _auto_granularity("2026-01-01 to 2026-01-10") == "daily"


class TestRenderChart:
    """Tests for render_chart tool"""

    @pytest.mark.asyncio
    async def test_render_chart_valid(self):
        from src.finout_mcp_server.server import render_chart_impl

        result = await render_chart_impl(
            {
                "title": "Top Costs",
                "chart_type": "bar",
                "categories": ["EC2", "RDS", "S3"],
                "series": [{"name": "Cost", "data": [22000, 12000, 8000]}],
            }
        )

        assert result["title"] == "Top Costs"
        assert result["chart_type"] == "bar"
        assert result["categories"] == ["EC2", "RDS", "S3"]
        assert len(result["series"]) == 1
        assert result["y_label"] == "Cost ($)"

    @pytest.mark.asyncio
    async def test_render_chart_missing_required_fields(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="Missing required fields"):
            await render_chart_impl({"title": "Test"})

    @pytest.mark.asyncio
    async def test_render_chart_invalid_chart_type(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="chart_type must be one of"):
            await render_chart_impl(
                {
                    "title": "Test",
                    "chart_type": "scatter",
                    "categories": ["A"],
                    "series": [{"name": "S", "data": [1]}],
                }
            )

    @pytest.mark.asyncio
    async def test_render_chart_invalid_series(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="series must be a non-empty array"):
            await render_chart_impl(
                {
                    "title": "Test",
                    "chart_type": "bar",
                    "categories": ["A"],
                    "series": [],
                }
            )

    @pytest.mark.asyncio
    async def test_render_chart_custom_labels(self):
        from src.finout_mcp_server.server import render_chart_impl

        result = await render_chart_impl(
            {
                "title": "Usage",
                "chart_type": "line",
                "categories": ["Jan", "Feb"],
                "series": [{"name": "Hours", "data": [100, 200]}],
                "x_label": "Month",
                "y_label": "Hours",
            }
        )

        assert result["x_label"] == "Month"
        assert result["y_label"] == "Hours"

    @pytest.mark.asyncio
    async def test_render_chart_series_length_must_match_categories(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="must match categories length"):
            await render_chart_impl(
                {
                    "title": "Mismatch",
                    "chart_type": "line",
                    "categories": ["Jan", "Feb", "Mar"],
                    "series": [{"name": "Cost", "data": [1, 2]}],
                }
            )

    @pytest.mark.asyncio
    async def test_render_chart_series_values_must_be_numbers(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="must be a number"):
            await render_chart_impl(
                {
                    "title": "Invalid Values",
                    "chart_type": "bar",
                    "categories": ["A", "B"],
                    "series": [{"name": "Cost", "data": [1, "two"]}],
                }
            )

    @pytest.mark.asyncio
    async def test_render_chart_pie_requires_single_series(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="pie charts must have exactly one series"):
            await render_chart_impl(
                {
                    "title": "Pie",
                    "chart_type": "pie",
                    "categories": ["A", "B"],
                    "series": [
                        {"name": "S1", "data": [1, 2]},
                        {"name": "S2", "data": [3, 4]},
                    ],
                }
            )

    @pytest.mark.asyncio
    async def test_render_chart_accepts_colors_and_per_series_color(self):
        from src.finout_mcp_server.server import render_chart_impl

        result = await render_chart_impl(
            {
                "title": "Colored",
                "chart_type": "bar",
                "categories": ["A", "B"],
                "colors": ["#38B28E", "#4B9BFF"],
                "series": [{"name": "Cost", "data": [1, 2], "color": "#FF8C42"}],
            }
        )

        assert result["colors"] == ["#38B28E", "#4B9BFF"]
        assert result["series"][0]["color"] == "#FF8C42"

    @pytest.mark.asyncio
    async def test_render_chart_accepts_multi_axis_line(self):
        from src.finout_mcp_server.server import render_chart_impl

        result = await render_chart_impl(
            {
                "title": "Cost vs Usage",
                "chart_type": "line",
                "categories": ["Jan", "Feb"],
                "y_axes": [
                    {"label": "Cost ($)", "opposite": False},
                    {"label": "Usage (hrs)", "opposite": True},
                ],
                "series": [
                    {"name": "Cost", "data": [100, 120], "y_axis": 0, "color": "#38B28E"},
                    {"name": "Usage", "data": [1000, 1200], "y_axis": 1, "color": "#4B9BFF"},
                ],
            }
        )

        assert result["y_axes"][0]["label"] == "Cost ($)"
        assert result["series"][1]["y_axis"] == 1

    @pytest.mark.asyncio
    async def test_render_chart_rejects_y_axis_without_y_axes(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="requires y_axes"):
            await render_chart_impl(
                {
                    "title": "Invalid",
                    "chart_type": "line",
                    "categories": ["Jan", "Feb"],
                    "series": [{"name": "Cost", "data": [1, 2], "y_axis": 0}],
                }
            )

    @pytest.mark.asyncio
    async def test_render_chart_rejects_y_axis_for_non_line(self):
        from src.finout_mcp_server.server import render_chart_impl

        with pytest.raises(ValueError, match="only supported for line charts"):
            await render_chart_impl(
                {
                    "title": "Invalid",
                    "chart_type": "bar",
                    "categories": ["A", "B"],
                    "series": [{"name": "Cost", "data": [1, 2], "y_axis": 0}],
                }
            )

    def test_render_chart_in_billy_tools(self):
        from src.finout_mcp_server.server import BILLY_INTERNAL_EXTRA_TOOLS

        assert "render_chart" in BILLY_INTERNAL_EXTRA_TOOLS

    @pytest.mark.asyncio
    async def test_render_chart_not_in_public_tools(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        server_module.runtime_mode = server_module.MCPMode.PUBLIC.value
        public_tools = await server_module.list_tools()
        public_tool_names = {t.name for t in public_tools}
        assert "render_chart" not in public_tool_names


class TestAnalyzeVirtualTagsHelpers:
    """Unit tests for analyze_virtual_tags helper functions."""

    def test_infer_tag_type_reallocation(self):
        from src.finout_mcp_server.server import _infer_tag_type

        tag = {"allocations": [{"type": "metric", "data": {"metricName": "ratio"}}]}
        assert _infer_tag_type(tag, {}) == "reallocation"

    def test_infer_tag_type_relational(self):
        from src.finout_mcp_server.server import _infer_tag_type

        tag_map = {"tag-id-1": "Other Tag"}
        tag = {"rules": [{"filters": {"costCenter": "virtualTag", "key": "tag-id-1"}}]}
        assert _infer_tag_type(tag, tag_map) == "relational"

    def test_infer_tag_type_custom(self):
        from src.finout_mcp_server.server import _infer_tag_type

        tag = {"rules": [{"filters": {"costCenter": "amazon-cur", "key": "service"}}]}
        assert _infer_tag_type(tag, {}) == "custom"

    def test_infer_tag_type_base(self):
        from src.finout_mcp_server.server import _infer_tag_type

        assert _infer_tag_type({}, {}) == "base"
        assert _infer_tag_type({"rules": []}, {}) == "base"

    def test_compute_summary_counts(self):
        from src.finout_mcp_server.server import _compute_summary

        tags = [
            {"id": "a"},
            {"id": "b"},
            {"id": "c"},
            {"id": "d"},
        ]
        tag_id_to_type = {"a": "custom", "b": "custom", "c": "reallocation", "d": "relational"}
        edges: dict[tuple[str, str], int] = {("a", "c"): 1, ("b", "c"): 1}
        summary = _compute_summary(tags, edges, tag_id_to_type)

        assert summary["total"] == 4
        assert summary["with_dependencies"] == 3  # a, b, c
        assert summary["isolated"] == 1  # d
        assert summary["by_type"]["custom"] == 2
        assert summary["by_type"]["reallocation"] == 1
        assert summary["by_type"]["relational"] == 1

    def test_notable_tags_sorted_by_score(self):
        from src.finout_mcp_server.server import _notable_tags

        tags = [
            {"id": "a", "name": "Alpha", "rules": [1, 2, 3]},
            {"id": "b", "name": "Beta", "rules": []},
            {"id": "c", "name": "Gamma", "rules": [1]},
        ]
        tag_map = {"a": "Alpha", "b": "Beta", "c": "Gamma"}
        tag_id_to_type = {"a": "custom", "b": "custom", "c": "relational"}
        edges: dict[tuple[str, str], int] = {("a", "c"): 1, ("b", "c"): 1}

        result = _notable_tags(tags, edges, tag_map, tag_id_to_type)
        names = [r["name"] for r in result]
        # c is used_by=2 → score 4; a has depends_on=1 + rules=3 → score 5; b depends_on=1 → score 2
        assert names[0] == "Alpha"
        assert names[1] == "Gamma"

    def test_notable_tags_excludes_isolated(self):
        from src.finout_mcp_server.server import _notable_tags

        tags = [{"id": "a", "name": "Alpha", "rules": []}]
        tag_map = {"a": "Alpha"}
        tag_id_to_type = {"a": "base"}
        edges: dict[tuple[str, str], int] = {}

        result = _notable_tags(tags, edges, tag_map, tag_id_to_type)
        assert result == []

    def test_get_reallocation_info_metric(self):
        from src.finout_mcp_server.server import _get_reallocation_info

        tag = {
            "allocations": [
                {
                    "name": "my-split",
                    "type": "metric",
                    "data": {
                        "metricName": "ratio",
                        "kpiCenterId": "kpi-123",
                        "tagName": "namespace",
                        "joinField": "name_skeleton",
                    },
                }
            ]
        }
        info = _get_reallocation_info(tag)

        assert info["strategy"] == "metric"
        assert len(info["metric_sources"]) == 1
        assert info["metric_sources"][0]["metric"] == "ratio"
        assert info["metric_sources"][0]["dimension"] == "namespace"
        assert info["metric_sources"][0]["join_on"] == "name_skeleton"
        assert info["allocation_count"] == 1

    def test_get_reallocation_info_percentage(self):
        from src.finout_mcp_server.server import _get_reallocation_info

        tag = {"allocations": [{"type": "percentage", "targets": ["team-a", "team-b"]}]}
        info = _get_reallocation_info(tag)

        assert info["strategy"] == "percentage"
        assert info["allocation_count"] == 1

    def test_get_reallocation_info_empty(self):
        from src.finout_mcp_server.server import _get_reallocation_info

        assert _get_reallocation_info({}) == {
            "strategy": "unknown",
            "metric_sources": [],
            "allocation_count": 0,
        }
        assert _get_reallocation_info({"allocations": []}) == {
            "strategy": "unknown",
            "metric_sources": [],
            "allocation_count": 0,
        }


class TestFindClosestValues:
    """Tests for _find_closest_values helper."""

    def test_exact_match(self):
        from src.finout_mcp_server.server import _find_closest_values

        result = _find_closest_values("AmazonEC2", ["AmazonEC2", "AmazonS3", "AmazonRDS"])
        assert result[0] == "AmazonEC2"

    def test_substring_match(self):
        from src.finout_mcp_server.server import _find_closest_values

        result = _find_closest_values("ec2", ["AmazonEC2", "AmazonS3", "AmazonRDS"])
        assert "AmazonEC2" in result

    def test_reverse_substring(self):
        from src.finout_mcp_server.server import _find_closest_values

        result = _find_closest_values("AmazonEC2Instance", ["AmazonEC2", "AmazonS3"])
        assert "AmazonEC2" in result

    def test_character_overlap(self):
        from src.finout_mcp_server.server import _find_closest_values

        result = _find_closest_values("s3", ["AmazonS3", "AmazonEC2", "AmazonRDS"])
        assert len(result) > 0

    def test_no_match(self):
        from src.finout_mcp_server.server import _find_closest_values

        result = _find_closest_values("zzzzz", ["AmazonEC2", "AmazonS3"])
        # May return empty or low-score results
        assert isinstance(result, list)

    def test_top_n_limit(self):
        from src.finout_mcp_server.server import _find_closest_values

        values = [f"Service{i}" for i in range(20)]
        result = _find_closest_values("Service", values, top_n=3)
        assert len(result) <= 3


class TestValidateFilterValues:
    """Tests for _validate_filter_values."""

    @pytest.mark.asyncio
    async def test_exact_match_passes(self):
        from src.finout_mcp_server.server import _validate_filter_values

        client = Mock()
        client.get_filter_values = AsyncMock(return_value=["AmazonEC2", "AmazonS3", "AmazonRDS"])

        filters = [
            {"key": "service", "costCenter": "amazon-cur", "type": "col", "value": "AmazonEC2"}
        ]
        corrected, warnings = await _validate_filter_values(client, filters)
        assert corrected[0]["value"] == "AmazonEC2"
        assert warnings == []

    @pytest.mark.asyncio
    async def test_case_correction(self):
        from src.finout_mcp_server.server import _validate_filter_values

        client = Mock()
        client.get_filter_values = AsyncMock(return_value=["AmazonEC2", "AmazonS3"])

        filters = [
            {"key": "service", "costCenter": "amazon-cur", "type": "col", "value": "amazonec2"}
        ]
        corrected, warnings = await _validate_filter_values(client, filters)
        assert corrected[0]["value"] == "AmazonEC2"
        assert len(warnings) == 1
        assert "auto-corrected" in warnings[0]

    @pytest.mark.asyncio
    async def test_fabricated_value_raises(self):
        from src.finout_mcp_server.server import _validate_filter_values

        client = Mock()
        client.get_filter_values = AsyncMock(return_value=["AmazonEC2", "AmazonS3", "AmazonRDS"])

        filters = [{"key": "service", "costCenter": "amazon-cur", "type": "col", "value": "ec2"}]
        with pytest.raises(ValueError, match="value 'ec2' not found"):
            await _validate_filter_values(client, filters)

    @pytest.mark.asyncio
    async def test_oneof_validates_each(self):
        from src.finout_mcp_server.server import _validate_filter_values

        client = Mock()
        client.get_filter_values = AsyncMock(return_value=["AmazonEC2", "AmazonS3", "AmazonRDS"])

        filters = [
            {
                "key": "service",
                "costCenter": "amazon-cur",
                "type": "col",
                "operator": "oneOf",
                "value": ["AmazonEC2", "amazons3"],
            }
        ]
        corrected, warnings = await _validate_filter_values(client, filters)
        assert corrected[0]["value"] == ["AmazonEC2", "AmazonS3"]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_api_error_skips_validation(self):
        from src.finout_mcp_server.server import _validate_filter_values

        client = Mock()
        client.get_filter_values = AsyncMock(side_effect=Exception("API error"))

        filters = [
            {"key": "service", "costCenter": "amazon-cur", "type": "col", "value": "anything"}
        ]
        corrected, warnings = await _validate_filter_values(client, filters)
        assert corrected[0]["value"] == "anything"
        assert len(warnings) == 1
        assert "validation skipped" in warnings[0]


class TestValueBasedSearch:
    """Tests for value-based search in search_filters_by_keyword."""

    def test_finds_filter_by_value_match(self):
        from src.finout_mcp_server.filter_utils import search_filters_by_keyword

        metadata = {
            "virtualTag": {
                "col": [
                    {
                        "key": "396533f6-uuid",
                        "path": "Virtual Tags/Cloud Provider - Reporting",
                        "values": {"GCP Marketplace": {}, "AWS Marketplace": {}, "AWS": {}},
                    },
                ]
            },
        }
        results = search_filters_by_keyword(metadata, "marketplace")
        assert len(results) == 1
        assert results[0]["key"] == "396533f6-uuid"
        assert "matched_values" in results[0]
        assert "GCP Marketplace" in results[0]["matched_values"]
        assert "AWS Marketplace" in results[0]["matched_values"]

    def test_value_match_lower_priority_than_key_match(self):
        from src.finout_mcp_server.filter_utils import search_filters_by_keyword

        metadata = {
            "amazon-cur": {
                "col": [
                    {
                        "key": "marketplace_flag",
                        "path": "AWS/Marketplace Flag",
                        "values": {},
                    },
                ]
            },
            "virtualTag": {
                "col": [
                    {
                        "key": "some-uuid",
                        "path": "Virtual Tags/Provider",
                        "values": {"AWS Marketplace": {}, "GCP Marketplace": {}},
                    },
                ]
            },
        }
        results = search_filters_by_keyword(metadata, "marketplace")
        assert len(results) == 2
        # Key match should rank higher than value match
        assert results[0]["key"] == "marketplace_flag"
        assert results[1]["key"] == "some-uuid"

    def test_no_value_match_returns_empty(self):
        from src.finout_mcp_server.filter_utils import search_filters_by_keyword

        metadata = {
            "amazon-cur": {
                "col": [
                    {"key": "service", "path": "AWS/Service", "values": {"AmazonEC2": {}}},
                ]
            },
        }
        results = search_filters_by_keyword(metadata, "nonexistent")
        assert len(results) == 0

    def test_value_match_with_list_values(self):
        from src.finout_mcp_server.filter_utils import search_filters_by_keyword

        metadata = {
            "amazon-cur": {
                "col": [
                    {
                        "key": "billing_entity",
                        "path": "AWS/Billing Entity",
                        "values": ["AWS", "AWS Marketplace"],
                    },
                ]
            },
        }
        results = search_filters_by_keyword(metadata, "marketplace")
        assert len(results) == 1
        assert "AWS Marketplace" in results[0]["matched_values"]

    def test_matched_values_capped_at_5(self):
        from src.finout_mcp_server.filter_utils import search_filters_by_keyword

        metadata = {
            "virtualTag": {
                "col": [
                    {
                        "key": "uuid",
                        "path": "Virtual Tags/Test",
                        "values": {f"marketplace-{i}": {} for i in range(20)},
                    },
                ]
            },
        }
        results = search_filters_by_keyword(metadata, "marketplace")
        assert len(results) == 1
        assert len(results[0]["matched_values"]) == 5

    def test_format_search_results_shows_matched_values(self):
        from src.finout_mcp_server.filter_utils import format_search_results

        results = [
            {
                "key": "some-uuid",
                "type": "col",
                "costCenter": "virtualTag",
                "path": "Virtual Tags/Provider",
                "relevance": 20,
                "value_count": 5,
                "matched_values": ["AWS Marketplace", "GCP Marketplace"],
            }
        ]
        formatted = format_search_results(results)
        assert "Matched values:" in formatted
        assert "AWS Marketplace" in formatted
        assert "GCP Marketplace" in formatted


class TestFormatSearchResultsWithSamples:
    """Tests for format_search_results with sample values."""

    def test_renders_sample_values(self):
        from src.finout_mcp_server.filter_utils import format_search_results

        results = [
            {
                "key": "service",
                "type": "col",
                "costCenter": "amazon-cur",
                "path": "AWS/Services",
                "relevance": 100,
                "value_count": 45,
            }
        ]
        sample_values = {"amazon-cur:col:service": ["AmazonEC2", "AmazonS3", "AmazonRDS"]}
        formatted = format_search_results(results, sample_values=sample_values)
        assert "AmazonEC2" in formatted
        assert "AmazonS3" in formatted
        assert "Values:" in formatted

    def test_no_samples_still_works(self):
        from src.finout_mcp_server.filter_utils import format_search_results

        results = [
            {
                "key": "region",
                "type": "col",
                "costCenter": "amazon-cur",
                "path": "AWS/Regions",
                "relevance": 80,
                "value_count": 20,
            }
        ]
        formatted = format_search_results(results)
        assert "region" in formatted
        assert "Values:" not in formatted

    def test_groups_by_cost_center_and_type(self):
        from src.finout_mcp_server.filter_utils import format_search_results

        results = [
            {
                "key": "service",
                "type": "col",
                "costCenter": "amazon-cur",
                "path": "AWS/Services",
                "relevance": 100,
                "value_count": 45,
            },
            {
                "key": "env",
                "type": "tag",
                "costCenter": "amazon-cur",
                "path": "AWS/Tags/env",
                "relevance": 80,
                "value_count": 3,
            },
            {
                "key": "project",
                "type": "col",
                "costCenter": "GCP",
                "path": "GCP/Projects",
                "relevance": 60,
                "value_count": 10,
            },
        ]
        formatted = format_search_results(results)
        assert "## amazon-cur" in formatted
        assert "## GCP" in formatted
        assert "### col" in formatted
        assert "### tag" in formatted


SAMPLE_METADATA = {
    "amazon-cur": {
        "col": [
            {"key": "service", "path": "AMAZON-CUR/Service", "values": {}},
            {"key": "region", "path": "AMAZON-CUR/Region", "values": {}},
        ],
        "finrichment": [
            {"key": "finrichment_product_name", "path": "AWS/Product Name", "values": {}},
        ],
        "tag": [
            {"key": "environment", "path": "AWS/Tags/environment", "values": {}},
        ],
    },
    "GCP": {
        "col": [
            {"key": "service", "path": "GCP/Service", "values": {}},
        ],
    },
}


class TestValidateFilterMetadata:
    """Tests for _validate_filter_metadata."""

    @pytest.mark.asyncio
    async def test_exact_metadata_passes(self):
        from src.finout_mcp_server.server import _validate_filter_metadata

        client = Mock()
        client.get_filters_metadata = AsyncMock(return_value=SAMPLE_METADATA)

        filters = [
            {
                "key": "finrichment_product_name",
                "costCenter": "amazon-cur",
                "type": "finrichment",
                "path": "AWS/Product Name",
                "value": "Amazon Elastic Compute Cloud",
            }
        ]
        corrected, warnings = await _validate_filter_metadata(client, filters)
        assert corrected[0]["type"] == "finrichment"
        assert corrected[0]["path"] == "AWS/Product Name"
        assert warnings == []

    @pytest.mark.asyncio
    async def test_wrong_type_auto_corrected(self):
        """The exact bug: Claude sends type='col' when it should be 'finrichment'."""
        from src.finout_mcp_server.server import _validate_filter_metadata

        client = Mock()
        client.get_filters_metadata = AsyncMock(return_value=SAMPLE_METADATA)

        filters = [
            {
                "key": "finrichment_product_name",
                "costCenter": "amazon-cur",
                "type": "col",
                "path": "AMAZON-CUR/Product",
                "value": "Amazon Elastic Compute Cloud",
            }
        ]
        corrected, warnings = await _validate_filter_metadata(client, filters)
        assert corrected[0]["type"] == "finrichment"
        assert corrected[0]["path"] == "AWS/Product Name"
        assert len(warnings) == 1
        assert "auto-corrected" in warnings[0]

    @pytest.mark.asyncio
    async def test_wrong_path_auto_corrected(self):
        from src.finout_mcp_server.server import _validate_filter_metadata

        client = Mock()
        client.get_filters_metadata = AsyncMock(return_value=SAMPLE_METADATA)

        filters = [
            {
                "key": "service",
                "costCenter": "amazon-cur",
                "type": "col",
                "path": "wrong/path",
                "value": "AmazonEC2",
            }
        ]
        corrected, warnings = await _validate_filter_metadata(client, filters)
        assert corrected[0]["path"] == "AMAZON-CUR/Service"
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_key_not_in_cost_center_but_exists_elsewhere(self):
        from src.finout_mcp_server.server import _validate_filter_metadata

        client = Mock()
        client.get_filters_metadata = AsyncMock(return_value=SAMPLE_METADATA)

        filters = [
            {
                "key": "environment",
                "costCenter": "GCP",
                "type": "tag",
                "path": "GCP/Tags/environment",
                "value": "production",
            }
        ]
        with pytest.raises(ValueError, match="not found in cost center 'GCP'"):
            await _validate_filter_metadata(client, filters)

    @pytest.mark.asyncio
    async def test_key_not_found_anywhere(self):
        from src.finout_mcp_server.server import _validate_filter_metadata

        client = Mock()
        client.get_filters_metadata = AsyncMock(return_value=SAMPLE_METADATA)

        filters = [
            {
                "key": "nonexistent_filter",
                "costCenter": "amazon-cur",
                "type": "col",
                "path": "whatever",
                "value": "x",
            }
        ]
        with pytest.raises(ValueError, match="not found"):
            await _validate_filter_metadata(client, filters)

    @pytest.mark.asyncio
    async def test_metadata_api_error_skips_validation(self):
        from src.finout_mcp_server.server import _validate_filter_metadata

        client = Mock()
        client.get_filters_metadata = AsyncMock(side_effect=Exception("API error"))

        filters = [
            {
                "key": "service",
                "costCenter": "amazon-cur",
                "type": "col",
                "path": "whatever",
                "value": "x",
            }
        ]
        corrected, warnings = await _validate_filter_metadata(client, filters)
        # Should pass through unchanged but with a warning
        assert corrected[0]["type"] == "col"
        assert len(warnings) == 1
        assert "validation skipped" in warnings[0]

    @pytest.mark.asyncio
    async def test_ambiguous_key_raises(self):
        """When a key exists under multiple types, should fail instead of guessing."""
        from src.finout_mcp_server.server import _validate_filter_metadata

        ambiguous_metadata = {
            "amazon-cur": {
                "col": [
                    {"key": "product_name", "path": "AMAZON-CUR/Product", "values": {}},
                ],
                "finrichment": [
                    {"key": "product_name", "path": "AWS/Product Name", "values": {}},
                ],
            },
        }
        client = Mock()
        client.get_filters_metadata = AsyncMock(return_value=ambiguous_metadata)

        filters = [
            {
                "key": "product_name",
                "costCenter": "amazon-cur",
                "type": "tag",
                "path": "wrong",
                "value": "x",
            }
        ]
        with pytest.raises(ValueError, match="matches multiple filters"):
            await _validate_filter_metadata(client, filters)

    @pytest.mark.asyncio
    async def test_case_mismatch_in_same_cost_center_auto_corrected(self):
        from src.finout_mcp_server.server import _validate_filter_metadata

        client = Mock()
        client.get_filters_metadata = AsyncMock(return_value=SAMPLE_METADATA)

        filters = [
            {
                "key": "Service",
                "costCenter": "amazon-cur",
                "type": "tag",
                "path": "wrong/path",
                "value": "AmazonEC2",
            }
        ]
        corrected, warnings = await _validate_filter_metadata(client, filters)
        assert corrected[0]["type"] == "col"
        assert corrected[0]["path"] == "AMAZON-CUR/Service"
        assert len(warnings) == 1
        assert "auto-corrected" in warnings[0]


class TestSearchFiltersImpl:
    @pytest.mark.asyncio
    async def test_skips_incomplete_rows_for_copy_paste_filters(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def search_filters(self, query, cost_center, limit=50):
                return [
                    {
                        "costCenter": "amazon-cur",
                        "key": "service",
                        "path": "AMAZON-CUR/Service",
                        "type": "col",
                        "value_count": 10,
                    },
                    {
                        "costCenter": "amazon-cur",
                        "key": "broken",
                        # missing path/type intentionally
                    },
                ]

            async def get_filter_values(self, filter_key, cost_center, filter_type, limit=8):
                return ["AmazonEC2", "AmazonS3"]

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.search_filters_impl({"query": "service"})
        finally:
            server_module.finout_client = original_client

        assert result["result_count"] == 2
        assert len(result["filters"]) == 1
        assert result["filters"][0] == {
            "costCenter": "amazon-cur",
            "key": "service",
            "path": "AMAZON-CUR/Service",
            "type": "col",
        }


class TestCrossProviderGapDetection:
    """Tests for cross-provider gap detection in search_filters and query_costs."""

    @pytest.mark.asyncio
    async def test_search_filters_gap_note_when_partial_provider_match(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def search_filters(self, query, cost_center, limit=50):
                return [
                    {
                        "costCenter": "amazon-cur",
                        "key": "marketplace",
                        "path": "AMAZON-CUR/Marketplace",
                        "type": "col",
                        "value_count": 5,
                    },
                ]

            async def get_filter_values(self, filter_key, cost_center, filter_type, limit=8):
                return ["AWS Marketplace"]

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {
                        "col": [{"key": "marketplace", "path": "AMAZON-CUR/Marketplace"}]
                    },
                    "gcp": {"col": [{"key": "seller_name", "path": "GCP/Seller"}]},
                }

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.search_filters_impl({"query": "marketplace"})
        finally:
            server_module.finout_client = original_client

        assert "cross_provider_note" in result
        assert "gcp" in result["cross_provider_note"]
        assert "amazon-cur" in result["cross_provider_note"]

    @pytest.mark.asyncio
    async def test_search_filters_no_gap_note_when_cost_center_specified(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def search_filters(self, query, cost_center, limit=50):
                return [
                    {
                        "costCenter": "amazon-cur",
                        "key": "marketplace",
                        "path": "AMAZON-CUR/Marketplace",
                        "type": "col",
                        "value_count": 5,
                    },
                ]

            async def get_filter_values(self, filter_key, cost_center, filter_type, limit=8):
                return ["AWS Marketplace"]

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {"col": []},
                    "gcp": {"col": []},
                }

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.search_filters_impl(
                {"query": "marketplace", "cost_center": "amazon-cur"}
            )
        finally:
            server_module.finout_client = original_client

        assert "cross_provider_note" not in result

    @pytest.mark.asyncio
    async def test_search_filters_no_gap_note_when_all_providers_match(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def search_filters(self, query, cost_center, limit=50):
                return [
                    {
                        "costCenter": "amazon-cur",
                        "key": "service",
                        "path": "AMAZON-CUR/Service",
                        "type": "col",
                    },
                    {
                        "costCenter": "gcp",
                        "key": "service",
                        "path": "GCP/Service",
                        "type": "col",
                    },
                ]

            async def get_filter_values(self, filter_key, cost_center, filter_type, limit=8):
                return ["SomeService"]

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {"col": []},
                    "gcp": {"col": []},
                }

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.search_filters_impl({"query": "service"})
        finally:
            server_module.finout_client = original_client

        assert "cross_provider_note" not in result

    @pytest.mark.asyncio
    async def test_query_costs_exclusion_warning_subset(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {
                        "col": [
                            {"key": "marketplace", "path": "AMAZON-CUR/Marketplace", "type": "col"}
                        ]
                    },
                    "gcp": {"col": [{"key": "service", "path": "GCP/Service", "type": "col"}]},
                }

            async def get_filter_values(
                self, filter_key, cost_center=None, filter_type=None, limit=100
            ):
                return ["val1", "val2"]

            async def query_costs_with_filters(self, **kwargs):
                return [{"Sum(Net Amortized Cost)": 1000}]

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.query_costs_impl(
                {
                    "time_period": "last_30_days",
                    "filters": [
                        {
                            "costCenter": "amazon-cur",
                            "key": "marketplace",
                            "path": "AMAZON-CUR/Marketplace",
                            "type": "col",
                            "operator": "not",
                            "value": "val1",
                        },
                        {
                            "costCenter": "gcp",
                            "key": "service",
                            "path": "GCP/Service",
                            "type": "col",
                            "operator": "is",
                            "value": "val2",
                        },
                    ],
                }
            )
        finally:
            server_module.finout_client = original_client

        assert "_validation_warnings" in result
        warnings_text = " ".join(result["_validation_warnings"])
        assert "Exclusion filters only target" in warnings_text
        assert "gcp" in warnings_text

    @pytest.mark.asyncio
    async def test_query_costs_no_exclusion_warning_when_no_exclusions(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {
                        "col": [{"key": "service", "path": "AMAZON-CUR/Service", "type": "col"}]
                    },
                }

            async def get_filter_values(
                self, filter_key, cost_center=None, filter_type=None, limit=100
            ):
                return ["AmazonEC2"]

            async def query_costs_with_filters(self, **kwargs):
                return [{"Sum(Net Amortized Cost)": 500}]

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.query_costs_impl(
                {
                    "time_period": "last_30_days",
                    "filters": [
                        {
                            "costCenter": "amazon-cur",
                            "key": "service",
                            "path": "AMAZON-CUR/Service",
                            "type": "col",
                            "operator": "is",
                            "value": "AmazonEC2",
                        },
                    ],
                }
            )
        finally:
            server_module.finout_client = original_client

        assert "_validation_warnings" not in result or not any(
            "Exclusion" in w for w in result.get("_validation_warnings", [])
        )


class TestFetchVirtualTagLiveValues:
    """Tests for _fetch_virtual_tag_live_values."""

    @pytest.mark.asyncio
    async def test_fetches_values_for_seed_tags(self):
        from src.finout_mcp_server.server import _fetch_virtual_tag_live_values

        client = Mock()
        client.get_filter_values = AsyncMock(return_value=["TeamA", "TeamB", "TeamC"])

        tag_map = {"id1": "Cost Center Tag", "id2": "Other Tag"}
        result = await _fetch_virtual_tag_live_values(client, {"id1"}, tag_map)

        assert "Cost Center Tag" in result
        assert result["Cost Center Tag"]["values"] == ["TeamA", "TeamB", "TeamC"]
        assert "truncated" not in result["Cost Center Tag"]
        client.get_filter_values.assert_called_once_with(
            filter_key="Cost Center Tag", cost_center="virtualTag", limit=50
        )

    @pytest.mark.asyncio
    async def test_skips_on_api_error(self):
        from src.finout_mcp_server.server import _fetch_virtual_tag_live_values

        client = Mock()
        client.get_filter_values = AsyncMock(side_effect=Exception("API error"))

        tag_map = {"id1": "Broken Tag"}
        result = await _fetch_virtual_tag_live_values(client, {"id1"}, tag_map)

        assert result == {}

    @pytest.mark.asyncio
    async def test_multiple_seed_tags_in_parallel(self):
        from src.finout_mcp_server.server import _fetch_virtual_tag_live_values

        async def mock_values(filter_key: str, **kwargs: object) -> list[str]:
            return [f"{filter_key}_val1", f"{filter_key}_val2"]

        client = Mock()
        client.get_filter_values = AsyncMock(side_effect=mock_values)

        tag_map = {"id1": "Tag A", "id2": "Tag B"}
        result = await _fetch_virtual_tag_live_values(client, {"id1", "id2"}, tag_map)

        assert "Tag A" in result
        assert "Tag B" in result
        assert client.get_filter_values.call_count == 2


class TestContextDiscoveryRefactor:
    @pytest.mark.asyncio
    async def test_views_and_data_explorers_do_not_crash(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"
            account_id = "acct-1"

            async def get_dashboards(self):
                return []

            async def get_views(self):
                return [
                    {"id": "view-1", "name": "Cost Overview", "configuration": {"query": {}}},
                ]

            async def get_data_explorers(self):
                return [
                    {"id": "de-1", "name": "Cost Explorer", "description": "Explore cost data"},
                ]

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.discover_context_impl(
                {
                    "query": "cost",
                    "include_dashboards": False,
                    "include_views": True,
                    "include_data_explorers": True,
                }
            )
        finally:
            server_module.finout_client = original_client

        assert len(result["views"]) == 1
        assert len(result["data_explorers"]) == 1

    @pytest.mark.asyncio
    async def test_summary_example_uses_valid_filter_workflow(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"
            account_id = "acct-1"

            async def get_dashboards(self):
                return [
                    {"id": "dash-1", "name": "Cost Dashboard", "widgets": [{"widgetId": "w-1"}]},
                ]

            async def get_widget(self, widget_id: str):
                assert widget_id == "w-1"
                return {
                    "name": "By Service",
                    "configuration": {
                        "filters": {"key": "service", "value": "AmazonEC2", "operator": "is"},
                        "groupBy": {"key": "service", "path": "AMAZON-CUR/Service", "type": "col"},
                    },
                }

            async def get_views(self):
                return []

            async def get_data_explorers(self):
                return []

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.discover_context_impl(
                {
                    "query": "cost",
                    "include_dashboards": True,
                    "include_views": False,
                    "include_data_explorers": False,
                }
            )
        finally:
            server_module.finout_client = original_client

        summary = result["summary"]
        assert "search_filters('service')" in summary
        assert "'operator': 'eq'" not in summary


class TestTopMoversImpl:
    """Tests for get_top_movers_impl."""

    @pytest.mark.asyncio
    async def test_top_movers_basic(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        call_count = 0

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {
                        "col": [{"key": "service", "path": "AWS/Services", "type": "col"}]
                    },
                }

            async def get_filter_values(
                self, filter_key, cost_center=None, filter_type=None, limit=100
            ):
                return []

            async def query_costs_with_filters(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Current period
                    return [
                        {"Services": "EC2", "Sum(Net Amortized Cost)": 5000},
                        {"Services": "S3", "Sum(Net Amortized Cost)": 3000},
                        {"Services": "RDS", "Sum(Net Amortized Cost)": 2000},
                    ]
                else:
                    # Comparison period
                    return [
                        {"Services": "EC2", "Sum(Net Amortized Cost)": 4000},
                        {"Services": "S3", "Sum(Net Amortized Cost)": 3500},
                        {"Services": "Lambda", "Sum(Net Amortized Cost)": 500},
                    ]

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_top_movers_impl(
                {
                    "time_period": "last_30_days",
                    "comparison_period": "last_60_days",
                    "group_by": [
                        {
                            "costCenter": "amazon-cur",
                            "key": "service",
                            "path": "AWS/Services",
                            "type": "col",
                        }
                    ],
                }
            )
        finally:
            server_module.finout_client = original_client

        assert "top_increases" in result
        assert "top_decreases" in result
        assert "total_delta" in result

        # EC2 increased by 1000
        increases = result["top_increases"]
        assert any(m["name"] == "EC2" and m["delta"] == 1000 for m in increases)

        # S3 decreased by 500
        decreases = result["top_decreases"]
        assert any(m["name"] == "S3" and m["delta"] == -500 for m in decreases)

        # RDS is new (not in comparison)
        assert "new_items" in result
        assert any(m["name"] == "RDS" for m in result["new_items"])

        # Lambda was removed (not in current)
        assert "removed_items" in result
        assert any(m["name"] == "Lambda" for m in result["removed_items"])

    @pytest.mark.asyncio
    async def test_top_movers_requires_group_by(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            with pytest.raises(ValueError, match="group_by is required"):
                await server_module.get_top_movers_impl({"time_period": "last_30_days"})
        finally:
            server_module.finout_client = original_client

    @pytest.mark.asyncio
    async def test_top_movers_auto_comparison_period(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        periods_queried = []

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {"amazon-cur": {"col": [{"key": "svc", "path": "A/S", "type": "col"}]}}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                periods_queried.append(kwargs.get("time_period"))
                return [{"Services": "EC2", "Sum(Net Amortized Cost)": 100}]

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_top_movers_impl(
                {
                    "time_period": "this_month",
                    "group_by": [
                        {"costCenter": "amazon-cur", "key": "svc", "path": "A/S", "type": "col"}
                    ],
                }
            )
        finally:
            server_module.finout_client = original_client

        # this_month is partial — comparison should be normalized to an absolute range,
        # not the full last_month
        assert " to " in result["comparison_period"], (
            "Comparison period should be normalized to an absolute range for partial this_month"
        )
        assert "_normalization_note" in result
        assert periods_queried[0] == "this_month"

    @pytest.mark.asyncio
    async def test_top_movers_partial_period_normalization(self):
        """this_month vs last_month should normalize to equivalent elapsed days."""
        import importlib
        from datetime import date, timedelta

        server_module = importlib.import_module("src.finout_mcp_server.server")

        periods_queried: list[str] = []

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {"amazon-cur": {"col": [{"key": "svc", "path": "A/S", "type": "col"}]}}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                periods_queried.append(kwargs.get("time_period", ""))
                return [{"Services": "EC2", "Sum(Net Amortized Cost)": 100}]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_top_movers_impl(
                {
                    "time_period": "this_month",
                    "comparison_period": "last_month",
                    "group_by": [
                        {"costCenter": "amazon-cur", "key": "svc", "path": "A/S", "type": "col"}
                    ],
                }
            )
        finally:
            server_module.finout_client = original

        # Comparison should be constrained to first N days of last_month
        today = date.today()
        elapsed = today.day
        last_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        expected_end = last_month_start + timedelta(days=elapsed - 1)
        expected_range = f"{last_month_start.isoformat()} to {expected_end.isoformat()}"

        assert result["comparison_period"] == expected_range
        assert "_normalization_note" in result
        assert str(elapsed) in result["_normalization_note"]
        # The constrained range was used when querying — not raw "last_month"
        assert "last_month" not in periods_queried


class TestUnitEconomicsImpl:
    """Tests for get_unit_economics_impl."""

    @pytest.mark.asyncio
    async def test_unit_economics_basic(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {
                        "col": [
                            {"key": "service", "path": "AWS/Services", "type": "col"},
                            {"key": "resource_id", "path": "AWS/ResourceId", "type": "col"},
                        ]
                    },
                }

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                # API returns count-distinct values as strings
                return [
                    {
                        "Services": "EC2",
                        "Sum(Net Amortized Cost)": 10000,
                        "Count Distinct(Resource ID)": "50",
                    },
                    {
                        "Services": "RDS",
                        "Sum(Net Amortized Cost)": 8000,
                        "Count Distinct(Resource ID)": "10",
                    },
                ]

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_unit_economics_impl(
                {
                    "time_period": "last_30_days",
                    "count_dimension": {
                        "costCenter": "amazon-cur",
                        "key": "resource_id",
                        "path": "AWS/ResourceId",
                        "type": "col",
                    },
                    "group_by": [
                        {
                            "costCenter": "amazon-cur",
                            "key": "service",
                            "path": "AWS/Services",
                            "type": "col",
                        }
                    ],
                }
            )
        finally:
            server_module.finout_client = original_client

        assert "summary" in result
        assert "data" in result
        assert result["summary"]["meaningful_items"] == 2
        # overall_cpu = (10000+8000) / (50+10) = 18000/60 = 300
        assert result["summary"]["overall_cost_per_unit"] == "$300.00"

        # EC2: 10000/50 = 200, RDS: 8000/10 = 800; sorted by cost_per_unit desc
        rds_row = result["data"][0]
        assert rds_row["name"] == "RDS"
        assert rds_row["cost_per_unit"] == 800.0
        ec2_row = result["data"][1]
        assert ec2_row["name"] == "EC2"
        assert ec2_row["cost_per_unit"] == 200.0

    @pytest.mark.asyncio
    async def test_unit_economics_requires_count_dimension(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            with pytest.raises(ValueError, match="count_dimension is required"):
                await server_module.get_unit_economics_impl({"time_period": "last_30_days"})
        finally:
            server_module.finout_client = original_client

    @pytest.mark.asyncio
    async def test_unit_economics_no_data(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                return []

        original_client = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_unit_economics_impl(
                {
                    "time_period": "last_30_days",
                    "count_dimension": {
                        "costCenter": "amazon-cur",
                        "key": "resource_id",
                        "path": "AWS/ResourceId",
                        "type": "col",
                    },
                }
            )
        finally:
            server_module.finout_client = original_client

        assert result["data"] == []
        assert "No data" in result["message"]


class TestCostPatternsImpl:
    @pytest.mark.asyncio
    async def test_cost_patterns_hourly_data(self):
        """When the API has hourly data, hour-of-day analysis is included."""
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                # Return hourly data for the hourly request; empty for daily fallback
                if kwargs.get("x_axis_group_by") == "hourly":
                    return [
                        {"Day": "2026-03-10T08:00:00", "Sum(Net Amortized Cost)": 100},
                        {"Day": "2026-03-10T14:00:00", "Sum(Net Amortized Cost)": 200},
                        {"Day": "2026-03-10T22:00:00", "Sum(Net Amortized Cost)": 50},
                    ]
                return []

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_cost_patterns_impl({"time_period": "last_7_days"})
        finally:
            server_module.finout_client = original

        assert result["granularity"] == "hourly"
        assert "hourly_average" in result
        assert "peak_hourly_cost" in result
        assert result["total_hourly_periods_analyzed"] == 3

    @pytest.mark.asyncio
    async def test_cost_patterns_falls_back_to_daily(self):
        """When hourly data is unavailable, falls back to daily and provides weekday/weekend."""
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        call_granularities: list[str] = []

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                g = kwargs.get("x_axis_group_by", "")
                call_granularities.append(g)
                if g == "hourly":
                    return []  # No hourly data
                # Daily data: Mon-Fri high, Sat-Sun low
                return [
                    {"Day": "2026-03-09", "Sum(Net Amortized Cost)": 700000},  # Mon
                    {"Day": "2026-03-10", "Sum(Net Amortized Cost)": 720000},  # Tue
                    {"Day": "2026-03-11", "Sum(Net Amortized Cost)": 710000},  # Wed
                    {"Day": "2026-03-07", "Sum(Net Amortized Cost)": 650000},  # Sat
                    {"Day": "2026-03-08", "Sum(Net Amortized Cost)": 630000},  # Sun
                ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_cost_patterns_impl({"time_period": "last_7_days"})
        finally:
            server_module.finout_client = original

        # Should have tried hourly first, then fallen back to daily
        assert "hourly" in call_granularities
        assert "daily" in call_granularities
        assert result["granularity"] == "daily"
        assert "daily_average" in result
        assert "weekday_vs_weekend" in result
        assert "day_of_week_average" in result
        # Weekday avg (~710K) should be higher than weekend avg (~640K)
        wd_we = result["weekday_vs_weekend"]
        assert wd_we["weekend_to_weekday_ratio"] < 1.0


class TestSavingsCoverageImpl:
    @pytest.mark.asyncio
    async def test_savings_coverage_basic(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                assert "savingsPlanEffectiveCost" in kwargs.get("billing_metrics", [])
                return [
                    {
                        "Services": "EC2",
                        "Sum(Net Amortized Cost)": 10000,
                        "Sum(Savings Plan Effective Cost)": 6000,
                        "Sum(Reservation Effective Cost)": 2000,
                    },
                ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_savings_coverage_impl({"time_period": "last_30_days"})
        finally:
            server_module.finout_client = original

        assert "summary" in result
        assert result["summary"]["overall_coverage_percent"] == 80.0


class TestTagCoverageImpl:
    @pytest.mark.asyncio
    async def test_tag_coverage_basic(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        call_count = 0

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Total cost query
                    return [{"Sum(Net Amortized Cost)": 10000}]
                else:
                    # Grouped by tag — tagged spend
                    return [
                        {"Team": "Alpha", "Sum(Net Amortized Cost)": 6000},
                        {"Team": "Beta", "Sum(Net Amortized Cost)": 2000},
                    ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_tag_coverage_impl(
                {
                    "time_period": "last_30_days",
                    "tag_dimension": {
                        "costCenter": "amazon-cur",
                        "key": "team",
                        "path": "AWS/Team",
                        "type": "tag",
                    },
                }
            )
        finally:
            server_module.finout_client = original

        assert result["summary"]["overall_coverage_percent"] == 80.0
        assert result["summary"]["untagged_cost"] == "$2,000.00"

    @pytest.mark.asyncio
    async def test_tag_coverage_requires_tag_dimension(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            with pytest.raises(ValueError, match="tag_dimension is required"):
                await server_module.get_tag_coverage_impl({"time_period": "last_30_days"})
        finally:
            server_module.finout_client = original


class TestBudgetStatusImpl:
    @pytest.mark.asyncio
    async def test_budget_status_basic(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_financial_plans(self, name=None, period=None):
                return [
                    {
                        "name": "AWS Budget",
                        "total_budget": 100000,
                        "total_forecast": 95000,
                        "cost_type": "netAmortizedCost",
                    }
                ]

            async def query_costs_with_filters(self, **kwargs):
                return [{"Sum(Net Amortized Cost)": 40000}]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_budget_status_impl({"period": "2026-3"})
        finally:
            server_module.finout_client = original

        assert len(result["plans"]) == 1
        plan = result["plans"][0]
        assert plan["plan_name"] == "AWS Budget"
        assert plan["budget"] == "$100,000.00"
        assert plan["actual_spend"] == "$40,000.00"
        assert plan["utilization_percent"] == 40.0


class TestCostStatisticsImpl:
    @pytest.mark.asyncio
    async def test_cost_statistics_basic(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                assert kwargs.get("x_axis_group_by") == "daily"
                return [
                    {"Day": "2026-03-01", "Sum(Net Amortized Cost)": 100},
                    {"Day": "2026-03-02", "Sum(Net Amortized Cost)": 200},
                    {"Day": "2026-03-03", "Sum(Net Amortized Cost)": 150},
                    {"Day": "2026-03-04", "Sum(Net Amortized Cost)": 300},
                    {"Day": "2026-03-05", "Sum(Net Amortized Cost)": 50},
                ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_cost_statistics_impl({"time_period": "last_7_days"})
        finally:
            server_module.finout_client = original

        assert "statistics" in result
        stats = result["statistics"][0]
        assert stats["name"] == "overall"
        assert stats["daily_mean"] == 160.0
        assert stats["daily_min"] == 50.0
        assert stats["daily_max"] == 300.0
        assert stats["days"] == 5

        assert result["peak_day"]["cost"] == "$300.00"
        assert result["trough_day"]["cost"] == "$50.00"


class TestListDataExplorersImpl:
    @pytest.mark.asyncio
    async def test_list_data_explorers_basic(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"
            account_id = "test-123"
            _account_info = {"name": "Test"}

            async def get_data_explorers(self):
                return [
                    {
                        "id": "exp-1",
                        "name": "Monthly K8s Costs",
                        "description": "Kubernetes costs by namespace",
                        "columns": [
                            {
                                "columnType": "measurement",
                                "aggregation": "sum",
                                "type": "netAmortizedCost",
                            },
                            {"columnType": "dimension", "dimension": {"key": "namespace"}},
                        ],
                    },
                    {
                        "id": "exp-2",
                        "name": "AWS by Service",
                        "columns": [
                            {
                                "columnType": "measurement",
                                "aggregation": "sum",
                                "type": "netAmortizedCost",
                            },
                        ],
                    },
                ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.list_data_explorers_impl({})
        finally:
            server_module.finout_client = original

        assert result["total"] == 2
        assert result["explorers"][0]["name"] == "Monthly K8s Costs"

    @pytest.mark.asyncio
    async def test_list_data_explorers_with_query(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"
            account_id = "test-123"
            _account_info = {"name": "Test"}

            async def get_data_explorers(self):
                return [
                    {"id": "1", "name": "K8s Costs", "columns": []},
                    {"id": "2", "name": "AWS Costs", "columns": []},
                ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.list_data_explorers_impl({"query": "k8s"})
        finally:
            server_module.finout_client = original

        assert result["total"] == 1
        assert result["explorers"][0]["name"] == "K8s Costs"


class TestInferPreviousPeriod:
    """Unit tests for _infer_previous_period."""

    def test_last_quarter_does_not_map_to_itself(self):
        from finout_mcp_server.tools.analytics import _infer_previous_period

        result = _infer_previous_period("last_quarter")
        assert result != "last_quarter", "last_quarter must not compare against itself"
        # Should be an absolute date range (two quarters ago)
        assert " to " in result

    def test_last_quarter_returns_prior_quarter_dates(self):
        from datetime import date, timedelta

        from finout_mcp_server.tools.analytics import _infer_previous_period

        result = _infer_previous_period("last_quarter")
        start_str, end_str = result.split(" to ")
        prev_start = date.fromisoformat(start_str)
        prev_end = date.fromisoformat(end_str)

        today = date.today()
        current_q_month = ((today.month - 1) // 3) * 3 + 1
        last_q_month = current_q_month - 3
        last_q_year = today.year
        if last_q_month <= 0:
            last_q_month += 12
            last_q_year -= 1
        last_q_start = date(last_q_year, last_q_month, 1)

        # prev_end must be the day before last_quarter's start
        assert prev_end == last_q_start - timedelta(days=1)
        # prev_start must be exactly 3 months before last_quarter's start
        assert prev_start.day == 1

    def test_simple_named_periods(self):
        from finout_mcp_server.tools.analytics import _infer_previous_period

        assert _infer_previous_period("today") == "yesterday"
        assert _infer_previous_period("this_week") == "last_week"
        assert _infer_previous_period("this_month") == "last_month"
        assert _infer_previous_period("last_week") == "two_weeks_ago"


class TestTagCoverageEmptyBuckets:
    """Tests that empty/null tag values are excluded from tagged spend."""

    @pytest.mark.asyncio
    async def test_empty_tag_values_excluded(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        call_count = 0

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {}

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Total cost query
                    return [{"Sum(Net Amortized Cost)": 10000}]
                else:
                    # Tag-grouped query — includes an empty-tag row (untagged spend)
                    return [
                        {"Team": "Alpha", "Sum(Net Amortized Cost)": 6000},
                        {"Team": "", "Sum(Net Amortized Cost)": 3000},  # empty = untagged
                        {"Team": "N/A", "Sum(Net Amortized Cost)": 1000},  # sentinel = untagged
                    ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_tag_coverage_impl(
                {
                    "time_period": "last_30_days",
                    "tag_dimension": {
                        "costCenter": "amazon-cur",
                        "key": "team",
                        "path": "AWS/Team",
                        "type": "tag",
                    },
                }
            )
        finally:
            server_module.finout_client = original

        # Only Alpha (6000) should count as tagged — empty and N/A rows are untagged
        assert result["summary"]["overall_coverage_percent"] == 60.0
        assert result["summary"]["tagged_cost"] == "$6,000.00"
        assert result["summary"]["untagged_cost"] == "$4,000.00"


class TestBudgetStatusMultiplePlans:
    """Tests that each plan uses its own cost_type for actual spend."""

    @pytest.mark.asyncio
    async def test_multiple_plans_with_different_cost_types(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        queries_made: list[dict] = []

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_financial_plans(self, name=None, period=None):
                return [
                    {
                        "name": "Net Amortized Plan",
                        "total_budget": 100000,
                        "total_forecast": None,
                        "cost_type": "netAmortizedCost",
                    },
                    {
                        "name": "Blended Plan",
                        "total_budget": 80000,
                        "total_forecast": None,
                        "cost_type": "blendedCost",
                    },
                ]

            async def query_costs_with_filters(self, **kwargs):
                queries_made.append({"cost_type": kwargs.get("cost_type")})
                if str(kwargs.get("cost_type", "")).lower().startswith("blended"):
                    return [{"Sum(Blended Cost)": 30000}]
                return [{"Sum(Net Amortized Cost)": 45000}]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_budget_status_impl({"period": "2026-3"})
        finally:
            server_module.finout_client = original

        # Two different cost types → two separate queries
        assert len(queries_made) == 2

        plans = {p["plan_name"]: p for p in result["plans"]}
        # Net amortized plan should see 45000 actual
        assert plans["Net Amortized Plan"]["actual_spend"] == "$45,000.00"
        # Blended plan should see 30000 actual (its own query)
        assert plans["Blended Plan"]["actual_spend"] == "$30,000.00"


class TestCostStatisticsGroupedPeakTrough:
    """Tests that peak/trough use daily totals, not individual grouped rows."""

    @pytest.mark.asyncio
    async def test_peak_trough_use_daily_totals_when_grouped(self):
        import importlib

        server_module = importlib.import_module("src.finout_mcp_server.server")

        class StubClient:
            internal_api_url = "http://localhost:3000"

            async def get_filters_metadata(self):
                return {
                    "amazon-cur": {
                        "col": [{"key": "service", "path": "AWS/Services", "type": "col"}]
                    }
                }

            async def get_filter_values(self, *a, **kw):
                return []

            async def query_costs_with_filters(self, **kwargs):
                # Two services per day. On 03-01: EC2=100, S3=50 → total 150.
                # On 03-02: EC2=200, S3=300 → total 500 (the true peak day).
                # On 03-03: EC2=80, S3=20 → total 100 (the true trough day).
                return [
                    {"Day": "2026-03-01", "Services": "EC2", "Sum(Net Amortized Cost)": 100},
                    {"Day": "2026-03-01", "Services": "S3", "Sum(Net Amortized Cost)": 50},
                    {"Day": "2026-03-02", "Services": "EC2", "Sum(Net Amortized Cost)": 200},
                    {"Day": "2026-03-02", "Services": "S3", "Sum(Net Amortized Cost)": 300},
                    {"Day": "2026-03-03", "Services": "EC2", "Sum(Net Amortized Cost)": 80},
                    {"Day": "2026-03-03", "Services": "S3", "Sum(Net Amortized Cost)": 20},
                ]

        original = server_module.finout_client
        server_module.finout_client = StubClient()
        try:
            result = await server_module.get_cost_statistics_impl(
                {
                    "time_period": "last_7_days",
                    "group_by": [
                        {
                            "costCenter": "amazon-cur",
                            "key": "service",
                            "path": "AWS/Services",
                            "type": "col",
                        }
                    ],
                }
            )
        finally:
            server_module.finout_client = original

        # Peak day should be 03-02 (total 500), not 03-02-S3 alone
        assert result["peak_day"]["date"] == "2026-03-02"
        assert result["peak_day"]["cost"] == "$500.00"
        # Trough day should be 03-03 (total 100)
        assert result["trough_day"]["date"] == "2026-03-03"
        assert result["trough_day"]["cost"] == "$100.00"


class TestPromptTemplates:
    @pytest.mark.asyncio
    async def test_monthly_cost_review_uses_existing_tools(self):
        from src.finout_mcp_server.prompts import get_prompt

        prompt = await get_prompt("monthly_cost_review")
        content = prompt["messages"][0]["content"]
        assert "query_costs" in content
        assert "get_cost_summary" not in content
