"""
Finout API Client - handles all interactions with the Finout REST API.
Implements authentication, request handling, and data formatting.
"""

import os
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .filter_cache import FilterCache

MASKED_HEADERS = {"x-finout-client-id", "x-finout-secret-key"}


class CostType(StrEnum):
    """Cost metric types supported by Finout"""

    NET_AMORTIZED = "netAmortizedCost"
    BLENDED = "blendedCost"
    UNBLENDED = "unblendedCost"
    AMORTIZED = "amortizedCost"


class Granularity(StrEnum):
    """Time granularity for cost queries"""

    DAILY = "daily"
    MONTHLY = "monthly"
    ACCUMULATED = "accumulated"


class InternalAuthMode(StrEnum):
    """Authentication mode for internal API calls."""

    AUTHORIZED_HEADERS = "authorized_headers"
    KEY_SECRET = "key_secret"


class FinoutClient:
    """
    Client for interacting with the Finout API.
    Handles authentication, rate limiting, and data transformation.
    """

    def __init__(
        self,
        client_id: str | None = None,
        secret_key: str | None = None,
        base_url: str = "https://app.finout.io/v1",
        internal_api_url: str | None = None,
        account_id: str | None = None,
        internal_auth_mode: InternalAuthMode | str = InternalAuthMode.AUTHORIZED_HEADERS,
        allow_missing_credentials: bool = False,
    ):
        """
        Initialize Finout API client.

        Args:
            client_id: Finout API client ID (or from FINOUT_CLIENT_ID env var)
            secret_key: Finout API secret key (or from FINOUT_SECRET_KEY env var)
            base_url: Base URL for Finout API
            internal_api_url: Internal cost-service API URL (or from FINOUT_INTERNAL_API_URL env var)
            account_id: Account ID for internal API (or from FINOUT_ACCOUNT_ID env var)
            internal_auth_mode: Auth mode for internal API calls:
                                - authorized_headers (default)
                                - key_secret
            allow_missing_credentials: If True, allows initialization without credentials
                                       (for testing/inspection only - API calls will fail)
        """
        self.client_id = client_id or os.getenv("FINOUT_CLIENT_ID")
        self.secret_key = secret_key or os.getenv("FINOUT_SECRET_KEY")
        self.base_url = base_url
        self.internal_api_url = internal_api_url or os.getenv("FINOUT_INTERNAL_API_URL")
        self.account_id = account_id or os.getenv("FINOUT_ACCOUNT_ID")
        self.internal_auth_mode = InternalAuthMode(internal_auth_mode)

        # Log account initialization
        import sys

        if self.account_id:
            print(f"✓ MCP initialized with account: {self.account_id}", file=sys.stderr)
        else:
            print(
                "✗ WARNING: MCP started without account_id! Cross-account data leak possible!",
                file=sys.stderr,
            )

        if not self.client_id or not self.secret_key:
            if not allow_missing_credentials:
                raise ValueError(
                    "Finout credentials not provided. Set FINOUT_CLIENT_ID and "
                    "FINOUT_SECRET_KEY environment variables or pass them to the constructor."
                )

        # Initialize HTTP client with credentials if available
        headers = {"Content-Type": "application/json"}
        if self.client_id:
            headers["x-finout-client-id"] = self.client_id
        if self.secret_key:
            headers["x-finout-secret-key"] = self.secret_key

        self._recent_curls: list[str] = []

        async def _capture_request(request: httpx.Request) -> None:
            self._recent_curls.append(self._request_to_curl(request))

        event_hooks: dict[str, list[Any]] = {"request": [_capture_request]}

        self.client = httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=30.0, event_hooks=event_hooks
        )

        self.internal_client: httpx.AsyncClient | None
        self._account_info: dict[str, Any] | None = None

        if self.internal_api_url:
            self.internal_client = httpx.AsyncClient(
                base_url=self.internal_api_url,
                timeout=30.0,
                event_hooks={"request": [_capture_request]},
            )
        else:
            self.internal_client = None

        self._filter_cache: FilterCache | None = None

    async def close(self):
        """Close the HTTP clients"""
        await self.client.aclose()
        if self.internal_client:
            await self.internal_client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @staticmethod
    def _request_to_curl(request: httpx.Request) -> str:
        """Convert an httpx Request to a replayable curl command."""
        parts = [f"curl -X {request.method}"]
        for key, value in request.headers.items():
            if key.lower() in MASKED_HEADERS:
                value = "***"
            parts.append(f"  -H '{key}: {value}'")
        body = request.content
        if body:
            try:
                body_str = body.decode("utf-8")
            except UnicodeDecodeError:
                body_str = "<binary>"
            parts.append(f"  -d '{body_str}'")
        parts.append(f"  '{request.url}'")
        return " \\\n".join(parts)

    def collect_curls(self) -> list[str]:
        """Return and clear captured curl commands."""
        curls = self._recent_curls.copy()
        self._recent_curls.clear()
        return curls

    def _parse_time_period(self, period: str) -> tuple[int, int]:
        """
        Convert human-readable time period to UNIX timestamps.

        Args:
            period: Time period string - supports:
                   - Predefined: 'today', 'yesterday', 'last_7_days', 'this_week', 'last_week',
                     'two_weeks_ago', 'last_30_days', 'last_month', 'this_month', etc.
                   - Custom range: 'YYYY-MM-DD to YYYY-MM-DD' (e.g., '2026-01-24 to 2026-01-31')
                   - ISO format: 'YYYY-MM-DDTHH:MM:SS to YYYY-MM-DDTHH:MM:SS'

        Returns:
            Tuple of (start_timestamp, end_timestamp)
        """
        # Check for custom date range format
        if " to " in period:
            try:
                start_str, end_str = period.split(" to ", 1)
                start_str = start_str.strip()
                end_str = end_str.strip()

                # Try parsing with different formats
                for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                    try:
                        start = datetime.strptime(start_str, fmt)
                        end = datetime.strptime(end_str, fmt)
                        # If time not specified, end should be end of day
                        if fmt == "%Y-%m-%d":
                            end = end.replace(hour=23, minute=59, second=59)
                        return int(start.timestamp()), int(end.timestamp())
                    except ValueError:
                        continue

                raise ValueError(f"Could not parse date range: {period}")
            except Exception as e:
                raise ValueError(
                    f"Invalid date range format: {period}\n"
                    f"Expected format: 'YYYY-MM-DD to YYYY-MM-DD'\n"
                    f"Example: '2026-01-24 to 2026-01-31'"
                ) from e

        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day)

        if period == "today":
            start = today_start
            end = now
        elif period == "yesterday":
            start = today_start - timedelta(days=1)
            end = today_start
        elif period == "last_7_days":
            start = today_start - timedelta(days=7)
            end = now
        elif period == "last_30_days":
            start = today_start - timedelta(days=30)
            end = now
        elif period == "this_week":
            # Monday of this week
            days_since_monday = today_start.weekday()
            start = today_start - timedelta(days=days_since_monday)
            end = now
        elif period == "last_week":
            # Monday to Sunday of last week
            days_since_monday = today_start.weekday()
            this_monday = today_start - timedelta(days=days_since_monday)
            last_monday = this_monday - timedelta(days=7)
            start = last_monday
            end = this_monday
        elif period == "two_weeks_ago" or period == "week_before_last":
            # Monday to Sunday of two weeks ago
            days_since_monday = today_start.weekday()
            this_monday = today_start - timedelta(days=days_since_monday)
            two_weeks_ago_monday = this_monday - timedelta(days=14)
            two_weeks_ago_end = this_monday - timedelta(days=7)
            start = two_weeks_ago_monday
            end = two_weeks_ago_end
        elif period == "this_month" or period == "month_to_date":
            start = datetime(now.year, now.month, 1)
            end = now
        elif period == "last_month":
            # First day of last month
            first_this_month = datetime(now.year, now.month, 1)
            last_month = first_this_month - timedelta(days=1)
            start = datetime(last_month.year, last_month.month, 1)
            end = first_this_month
        elif period == "last_quarter":
            # Simplified: last 90 days
            start = today_start - timedelta(days=90)
            end = now
        else:
            raise ValueError(
                f"Unknown time period: {period}\n\n"
                f"Supported values: today, yesterday, last_7_days, this_week, last_week, "
                f"two_weeks_ago, last_30_days, this_month, last_month, last_quarter"
            )

        return int(start.timestamp()), int(end.timestamp())

    async def get_anomalies(
        self, time_period: str = "last_7_days", severity: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Fetch detected cost anomalies.

        Args:
            time_period: Time period to check for anomalies
            severity: Filter by severity (e.g., 'high', 'medium', 'low')

        Returns:
            List of anomaly objects

        Note: Anomalies API endpoint not yet documented in Finout API docs.
              This is a placeholder implementation.
        """
        # TODO: Find the correct Finout anomalies API endpoint
        # Searched docs.finout.io but no API endpoint documented
        # Anomalies exist in UI but no programmatic access documented yet

        raise NotImplementedError(
            "Anomalies API endpoint not yet available in Finout API documentation. "
            "Please contact Finout support for anomaly detection API access."
        )

    async def get_costguard_scans(self) -> list[dict[str, Any]]:
        """
        Fetch CostGuard waste detection scans.

        Returns:
            List of scan objects with metadata

        API Doc: https://docs.finout.io/configuration/finout-api/costguard-api
        """
        response = await self.client.get("/cost-guard/scans")
        response.raise_for_status()

        result = response.json()

        # Return the scans array from the response
        return result.get("scans", [])

    async def get_waste_recommendations(
        self,
        scan_type: str | None = None,
        service: str | None = None,
        min_saving: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get waste and optimization recommendations from CostGuard.

        Args:
            scan_type: Type of scan (e.g., 'idle', 'rightsizing')
            service: Filter by cloud service (e.g., 'AWS', 'GCP', 'K8S')
            min_saving: Minimum monthly savings threshold

        Returns:
            List of recommendation objects

        API Doc: https://docs.finout.io/configuration/finout-api/costguard-api
        """
        scans = await self.get_costguard_scans()

        all_recommendations = []

        for scan in scans:
            # Apply filters based on scan metadata
            metadata = scan.get("scanMetadata", {})

            if scan_type and metadata.get("type", "").lower() != scan_type.lower():
                continue

            if service and metadata.get("costCenter", "").upper() != service.upper():
                continue

            # Get recommendations for this scan
            scan_id = scan.get("scanId")

            # Call the recommendations endpoint
            response = await self.client.post(
                "/cost-guard/scans-recommendations", json={"scanId": scan_id}
            )
            response.raise_for_status()

            result = response.json()

            # Process grouped data
            for group_data in result.get("data", []):
                for resource in group_data.get("resources", []):
                    yearly_savings = resource.get("resourceYearlyPotentialSavings", 0)
                    monthly_savings = yearly_savings / 12

                    # Apply min_saving filter
                    if min_saving and monthly_savings < min_saving:
                        continue

                    all_recommendations.append(
                        {
                            "scan_id": scan_id,
                            "scan_name": result.get("scanName"),
                            "scan_type": metadata.get("type"),
                            "cost_center": metadata.get("costCenter"),
                            "group": group_data.get("group"),
                            "resource_id": resource.get("resourceId"),
                            "resource_metadata": resource.get("resourceMetadata", {}),
                            "resource_waste": resource.get("resourceTotalWaste", 0),
                            "monthly_savings": monthly_savings,
                            "yearly_savings": yearly_savings,
                        }
                    )

        # Sort by monthly savings (highest first)
        all_recommendations.sort(key=lambda x: x["monthly_savings"], reverse=True)

        return all_recommendations

    @property
    def filter_cache(self) -> "FilterCache":
        """
        Lazy-initialize and return the filter cache.

        Returns:
            FilterCache instance

        Raises:
            ValueError: If internal API URL not configured
        """
        if not self.internal_api_url:
            raise ValueError(
                "Internal API URL not configured. Set FINOUT_INTERNAL_API_URL "
                "environment variable to your cost-service endpoint."
            )

        if self._filter_cache is None:
            from .filter_cache import FilterCache

            # Ensure account info is fetched before creating cache
            # This is a sync property but we'll handle async in the actual API calls
            self._filter_cache = FilterCache(self)

        return self._filter_cache

    def _current_date_range(self) -> dict[str, Any]:
        """
        Get current date range for filter queries (last 30 days).

        Returns:
            Dictionary with correct date format for API
        """
        return self._build_date_payload("last_30_days")

    async def _fetch_account_info(self) -> dict[str, Any]:
        """
        Fetch full account information from account-service.
        Required to get payerId and other context needed for internal API calls.

        Returns:
            Account object with payerId, generalConfig, featureFlags, etc.
        """
        if not self.internal_client or not self.account_id:
            raise ValueError("Internal API client and account_id required")

        headers = self._get_internal_headers(for_account_service=True)

        response = await self.internal_client.get(
            f"/account-service/account/{self.account_id}",
            headers=headers,
            params={
                "fields": [
                    "name",
                    "payerId",
                    "defaultContextId",
                    "generalConfig",
                    "featureFlags",
                    "groups",
                    "latestCompletedRunTimestamp",
                ]
            },
        )
        response.raise_for_status()
        return response.json()

    def _get_internal_headers(self, for_account_service: bool = False) -> dict[str, str]:
        """
        Get headers for internal API calls based on selected auth mode.

        Returns:
            Dictionary of headers
        """
        if not self.internal_client:
            raise ValueError("Internal API client not configured")

        if self.internal_auth_mode == InternalAuthMode.KEY_SECRET:
            headers: dict[str, str] = {}
            if self.client_id:
                headers["x-finout-client-id"] = self.client_id
            if self.secret_key:
                headers["x-finout-secret-key"] = self.secret_key
            if not headers:
                raise ValueError("Key/secret mode requires FINOUT_CLIENT_ID and FINOUT_SECRET_KEY.")
            return headers

        if not self.account_id:
            import sys

            print("✗ WARNING: Making API call without account_id!", file=sys.stderr)
            return {"authorized-user-roles": "admin"}

        if for_account_service:
            return {
                "authorized-user-roles": "admin",
                "authorized-account-id": self.account_id,
            }

        return {
            "authorized-user-roles": "admin",
            "authorized-account-id": self.account_id,
        }

    async def _fetch_filters_metadata(self, date: dict[str, int] | None = None) -> dict[str, Any]:
        """
        Fetch filter metadata WITHOUT values (internal method for cache).

        Args:
            date: Date range for filter query

        Returns:
            Filter metadata organized by cost center

        Raises:
            ValueError: If internal API not configured or request fails
        """
        if not self.internal_client:
            raise ValueError("Internal API client not configured. Set FINOUT_INTERNAL_API_URL.")

        # Fetch account info on first API call (if needed for headers)
        if self.account_id and not self._account_info:
            import sys

            print(f"→ Fetching account info for {self.account_id}...", file=sys.stderr)
            try:
                self._account_info = await self._fetch_account_info()
                print(
                    f"✓ Account info loaded: payerId={self._account_info.get('payerId')}",
                    file=sys.stderr,
                )
            except Exception as e:
                print(f"✗ Failed to fetch account info: {e}", file=sys.stderr)
                print("  Proceeding without full context - API calls may fail!", file=sys.stderr)

        if date is None:
            date = self._current_date_range()

        # Get headers with full account context
        headers = self._get_internal_headers()

        try:
            # Call the filters endpoint with includeValues=false
            payload = {
                "date": date,
                "includeValues": False,  # This prevents the 10MB response
            }

            response = await self.internal_client.post(
                "/cost-service/filters",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

            result = response.json()

            # SECURITY: Filter results by account (defensive measure)
            # The API should filter by account, but we add this as a safety layer
            if self.account_id and isinstance(result, list):
                original_count = len(result)
                result = [
                    item
                    for item in result
                    if item.get("accountId") == self.account_id or not item.get("accountId")
                ]
                filtered_count = original_count - len(result)
                if filtered_count > 0:
                    import sys

                    print(
                        f"⚠️  Filtered out {filtered_count} cross-account filters (security)",
                        file=sys.stderr,
                    )

            # API returns a list of filters, not a nested dict
            if isinstance(result, list):
                # Convert list format to our expected dict format
                # API returns: [{"costCenter": "aws", "key": "service", "path": "...", "values": {...}}, ...]
                # Keep ALL metadata so we can build proper filter payloads later

                organized: dict[str, Any] = {}
                for item in result:
                    if not isinstance(item, dict):
                        continue

                    cost_center = item.get("costCenter", "unknown")

                    # Get the filter type from the API response
                    # Tags will have type="tag", standard filters have type="col"
                    filter_type = item.get("type", "col")

                    # Initialize cost center if not exists
                    if cost_center not in organized:
                        organized[cost_center] = {}

                    # Initialize filter type list if not exists
                    if filter_type not in organized[cost_center]:
                        organized[cost_center][filter_type] = []

                    # Keep all filter metadata (except values)
                    filter_obj = {
                        "costCenter": cost_center,
                        "key": item.get("key", ""),
                        "path": item.get("path", ""),
                        "type": filter_type,  # Use actual type from API
                    }

                    organized[cost_center][filter_type].append(filter_obj)

                return organized

            # If it's already a dict, process it
            if isinstance(result, dict):
                # Strip out values from each filter
                cleaned_result: dict[str, Any] = {}
                for cost_center, filter_types in result.items():
                    if isinstance(filter_types, dict):
                        cleaned_result[cost_center] = {}
                        for filter_type, filters in filter_types.items():
                            if isinstance(filters, list):
                                cleaned_filters = []
                                for f in filters:
                                    if isinstance(f, dict):
                                        cleaned_filter = {
                                            k: v for k, v in f.items() if k != "values"
                                        }
                                        cleaned_filters.append(cleaned_filter)
                                cleaned_result[cost_center][filter_type] = cleaned_filters
                return cleaned_result

            raise ValueError(
                f"Invalid response format from filters API: expected dict or list, got {type(result)}"
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError(
                    "Authentication failed. Check your FINOUT_CLIENT_ID and FINOUT_SECRET_KEY."
                ) from e
            elif e.response.status_code == 403:
                raise ValueError(
                    "Access denied. Verify your credentials have permission to access the cost-service API."
                ) from e
            else:
                raise

        except httpx.TimeoutException as e:
            raise ValueError(
                "Request timed out. The filters API may be slow or unavailable."
            ) from e

    async def _fetch_filter_values(
        self,
        filter_key: str,
        cost_center: str | None = None,
        filter_type: str | None = None,
        date: dict[str, int] | None = None,
    ) -> list[Any]:
        """
        Fetch values for a specific filter (internal method for cache).

        Args:
            filter_key: Filter key to fetch values for
            cost_center: Cost center filter belongs to
            filter_type: Type of filter
            date: Date range for value query

        Returns:
            List of filter values
        """
        if not self.internal_client:
            raise ValueError("Internal API client not configured. Set FINOUT_INTERNAL_API_URL.")

        if date is None:
            date = self._current_date_range()

        # Get headers
        headers = self._get_internal_headers()

        # Call the filters endpoint with specific filter request
        payload = {"date": date, "includeValues": True, "filterKey": filter_key}

        if cost_center:
            payload["costCenter"] = cost_center
        if filter_type:
            payload["filterType"] = filter_type

        response = await self.internal_client.post(
            "/cost-service/filters",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()

        # API returns a list, not nested dict
        if isinstance(result, list):
            # Find the matching filter and extract its values
            for item in result:
                if not isinstance(item, dict):
                    continue

                if item.get("key") == filter_key:
                    # Check cost_center match if specified
                    if cost_center and item.get("costCenter") != cost_center:
                        continue

                    # Extract values - they're in a dict, we need the keys
                    values_dict = item.get("values", {})
                    if isinstance(values_dict, dict):
                        return list(values_dict.keys())
                    return []

        # Fallback: old dict format
        values: list[Any] = []
        if isinstance(result, dict):
            for cc, types in result.items():
                if cost_center and cc != cost_center:
                    continue

                if isinstance(types, dict):
                    for ft, filters in types.items():
                        if filter_type and ft != filter_type:
                            continue

                        if isinstance(filters, list):
                            for f in filters:
                                if f.get("key") == filter_key:
                                    values_dict = f.get("values", {})
                                    if isinstance(values_dict, dict):
                                        return list(values_dict.keys())
                                    return []

        return values

    async def get_filters_metadata(
        self,
        date: dict[str, int] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """
        Get filter metadata (without values) using cache.

        Args:
            date: Date range for filter query
            use_cache: Whether to use cached metadata

        Returns:
            Filter metadata organized by cost center
        """
        return await self.filter_cache.get_metadata(date, use_cache)

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
        Get values for a specific filter (lazy-loaded from cache).

        Args:
            filter_key: Filter key to fetch values for
            cost_center: Cost center filter belongs to (case-insensitive, will be normalized to lowercase)
            filter_type: Type of filter
            date: Date range for value query
            limit: Maximum number of values to return
            use_cache: Whether to use cached values

        Returns:
            List of filter values (truncated to limit)

        Note:
            cost_center will be automatically normalized to correct capitalization
            (e.g., "VIRTUALTAG" becomes "virtualTag", "AMAZON-CUR" becomes "amazon-cur")
        """
        # Normalize cost_center to correct capitalization
        if cost_center:
            cost_center = self._normalize_cost_center(cost_center)

        return await self.filter_cache.get_filter_values(
            filter_key, cost_center, filter_type, date, limit, use_cache
        )

    async def search_filters(
        self,
        query: str,
        cost_center: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search filters by keyword with relevance ranking.

        Args:
            query: Search query (case-insensitive)
            cost_center: Optional cost center to filter by (case-insensitive, will be normalized)
            limit: Maximum number of results

        Returns:
            List of matching filters, sorted by relevance
        """
        from .filter_utils import search_filters_by_keyword

        # Normalize cost_center to correct capitalization
        if cost_center:
            cost_center = self._normalize_cost_center(cost_center)

        # Get metadata
        metadata = await self.get_filters_metadata()

        # Search using utility function
        return search_filters_by_keyword(metadata, query, cost_center, limit)

    def _normalize_cost_center(self, cost_center: str) -> str:
        """
        Normalize cost center names to correct capitalization.
        The Finout API is case-sensitive, so we need exact matches.

        Args:
            cost_center: Cost center name in any case

        Returns:
            Properly capitalized cost center name
        """
        # Mapping of lowercase to correct capitalization
        known_cost_centers = {
            "virtualtag": "virtualTag",  # NOT "VIRTUALTAG"
            "amazon-cur": "amazon-cur",
            "kubernetes": "kubernetes",
            "gcp": "gcp",
            "azure": "azure",
            "datadog": "datadog",
            "snowflake": "snowflake",
            "mongodb": "mongodb",
            "confluent": "confluent",
            "databricks": "databricks",
        }

        # Normalize to lowercase for lookup
        normalized = cost_center.lower()

        # Return known mapping or original if unknown
        return known_cost_centers.get(normalized, cost_center)

    def _build_filter_payload(self, filters: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Convert filter arguments to internal API format.

        Args:
            filters: List of filter objects with costCenter, key, path, type, operator, value

        Returns:
            Filter dict in internal API format (single filter or AND wrapper)

        Example input:
            [
                {
                    "costCenter": "amazon-cur",
                    "key": "parent_cloud_service",
                    "path": "AWS/Services",
                    "type": "col",
                    "operator": "is",
                    "value": "AmazonEC2"
                }
            ]

        Example output (single filter):
            {
                "costCenter": "amazon-cur",
                "key": "parent_cloud_service",
                "path": "AWS/Services",
                "type": "col",
                "operator": "is",
                "value": "AmazonEC2"
            }

        Example output (multiple filters):
            {
                "AND": [
                    {...filter1...},
                    {...filter2...}
                ]
            }
        """
        if not filters:
            return {}

        formatted_filters = []

        for f in filters:
            if not isinstance(f, dict):
                raise ValueError(f"Filter must be a dictionary: {f}")

            # Validate required fields
            required = ["costCenter", "key", "path", "type", "value"]
            for field in required:
                if field not in f:
                    raise ValueError(f"Filter missing required field '{field}': {f}")

            # Build filter in correct format (normalize costCenter for API)
            formatted_filter = {
                "costCenter": self._normalize_cost_center(f["costCenter"]),
                "key": f["key"],
                "path": f["path"],
                "type": f.get("type", "col"),
                "operator": f.get("operator", "is"),
                "value": f["value"],  # Single value, not array
            }

            formatted_filters.append(formatted_filter)

        # Single filter: return as-is
        if len(formatted_filters) == 1:
            return formatted_filters[0]

        # Multiple filters: wrap in AND
        return {"AND": formatted_filters}

    def _build_date_payload(self, time_period: str) -> dict[str, Any]:
        """
        Build date payload for cost queries in the format the API expects.

        Args:
            time_period: Time period string

        Returns:
            Date dict with correct format
        """
        # Map time periods to relative ranges (API-native)
        relative_map = {
            "today": {"relativeRange": "today", "type": "day"},
            "yesterday": {"relativeRange": "yesterday", "type": "day"},
            "last_7_days": {"relativeRange": "last7Days", "type": "day"},
            "last_30_days": {"relativeRange": "last30Days", "type": "day"},
            "this_month": {"relativeRange": "currentMonth", "type": "month"},
            "month_to_date": {"relativeRange": "currentMonth", "type": "month"},
            "last_month": {"relativeRange": "previousMonth", "type": "month"},
            "last_quarter": {"relativeRange": "previousQuarter", "type": "quarter"},
        }

        if time_period in relative_map:
            return relative_map[time_period]

        # For custom periods (this_week, last_week, two_weeks_ago, etc.)
        # use absolute timestamps
        start_ts, end_ts = self._parse_time_period(time_period)
        return {
            "from": start_ts * 1000,
            "to": end_ts * 1000,
            "type": "day",  # Use "day" granularity for custom ranges
        }

    async def query_costs_with_filters(
        self,
        time_period: str = "last_30_days",
        filters: list[dict[str, Any]] | None = None,
        group_by: list[str] | None = None,
        x_axis_group_by: str | None = None,
        cost_type: CostType = CostType.NET_AMORTIZED,
        usage_configuration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Query costs/usage using internal API with flexible filters.

        Args:
            time_period: Time period string (e.g., 'last_30_days')
            filters: List of filter objects with key, value, operator
            group_by: List of dimensions to group by
            x_axis_group_by: X-axis grouping (e.g., "daily", "monthly")
            cost_type: Type of cost metric to retrieve
            usage_configuration: Usage config for querying usage instead of cost
                Example: {"usageType": "usageAmount", "costCenter": "amazon-cur", "units": "Hrs"}

        Returns:
            Cost/usage query results

        Raises:
            ValueError: If internal API not configured or invalid parameters
            httpx.HTTPStatusError: If API request fails
            httpx.TimeoutException: If request times out

        Example (cost query):
            await client.query_costs_with_filters(
                time_period="last_month",
                filters=[
                    {"key": "service", "value": ["ec2"], "operator": "eq"}
                ],
                x_axis_group_by="daily",
            )

        Example (usage query):
            await client.query_costs_with_filters(
                time_period="last_month",
                filters=[{"key": "service", "value": ["ec2"], "operator": "eq"}],
                usage_configuration={"usageType": "usageAmount", "costCenter": "amazon-cur", "units": "Hrs"}
            )
        """
        if not self.internal_client:
            raise ValueError(
                "Internal API client not configured. Set FINOUT_INTERNAL_API_URL "
                "environment variable to your cost-service endpoint."
            )

        # Get headers
        headers = self._get_internal_headers()

        try:
            # Build payload with correct date format
            payload: dict[str, Any] = {
                "date": self._build_date_payload(time_period),
                "costType": cost_type.value,
            }

            # Add filters if provided
            if filters:
                payload["filters"] = self._build_filter_payload(filters)

            # Add grouping if provided (needs full metadata like filters)
            if group_by:
                if not isinstance(group_by, list):
                    raise ValueError("group_by must be a list")
                # Normalize costCenter in group_by items
                normalized_group_by = []
                for group in group_by:
                    if isinstance(group, dict) and "costCenter" in group:
                        normalized_group = {**group}
                        normalized_group["costCenter"] = self._normalize_cost_center(
                            group["costCenter"]
                        )
                        normalized_group_by.append(normalized_group)
                    else:
                        normalized_group_by.append(group)
                payload["groupBys"] = normalized_group_by  # Note: plural "groupBys"

            if x_axis_group_by:
                if x_axis_group_by not in ["daily", "monthly"]:
                    raise ValueError("x_axis_group_by must be 'daily' or 'monthly'")
                payload["xAxisGroupBy"] = x_axis_group_by

            # Add usage configuration if provided (for usage queries instead of cost)
            if usage_configuration:
                payload["usageConfiguration"] = usage_configuration

            # Call internal cost API
            response = await self.internal_client.post(
                "/cost-service/cost", json=payload, headers=headers
            )
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                # Parse error response to help Claude understand what's wrong
                try:
                    error_body = e.response.json()
                    error_msg = (
                        error_body.get("message") or error_body.get("error") or str(error_body)
                    )
                except Exception:
                    error_msg = e.response.text or "Invalid request"

                raise ValueError(
                    f"Bad request (400): {error_msg}\n\n"
                    f"This usually means:\n"
                    f"- Invalid filter values (check filter values exist in the account)\n"
                    f"- Wrong operator (try 'eq' instead of 'is')\n"
                    f"- Missing required fields\n"
                    f"- Invalid time period format\n\n"
                    f"Suggestion: Try querying without filters first to test the time period."
                ) from e
            elif e.response.status_code == 401:
                raise ValueError(
                    "Authentication failed. Check your FINOUT_CLIENT_ID and FINOUT_SECRET_KEY."
                ) from e
            elif e.response.status_code == 403:
                raise ValueError(
                    "Access denied. Verify your credentials have permission to access the cost-service API."
                ) from e
            elif e.response.status_code == 404:
                raise ValueError(
                    "Cost-service API endpoint not found. Verify FINOUT_INTERNAL_API_URL is correct."
                ) from e
            else:
                raise

        except httpx.TimeoutException as e:
            raise ValueError(
                "Request timed out after 30 seconds. The API may be slow or unavailable."
            ) from e

    async def get_usage_unit_types(
        self,
        time_period: str = "last_30_days",
        filters: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """
        Discover available usage unit types for a cost center.

        Args:
            time_period: Time period for discovery
            filters: Filters to narrow down cost center (e.g., filter by cost_center_type)

        Returns:
            List of available units with costCenter
            Example: [{"costCenter": "GCP", "units": "Hour"}, {"costCenter": "GCP", "units": "Gibibyte"}]

        Raises:
            ValueError: If internal API not configured
            httpx.HTTPStatusError: If API request fails
        """
        if not self.internal_client:
            raise ValueError(
                "Internal API client not configured. Set FINOUT_INTERNAL_API_URL "
                "environment variable to your cost-service endpoint."
            )

        # Get headers
        headers = self._get_internal_headers()

        try:
            # Build payload
            payload: dict[str, Any] = {
                "date": self._build_date_payload(time_period),
                "groupBy": {},
            }

            # Add filters if provided
            if filters:
                payload["filters"] = self._build_filter_payload(filters)

            # Call usage unit types endpoint
            response = await self.internal_client.post(
                "/cost-service/usage-unit-types",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                try:
                    error_body = e.response.json()
                    error_msg = (
                        error_body.get("message") or error_body.get("error") or str(error_body)
                    )
                except Exception:
                    error_msg = e.response.text or "Invalid request"

                raise ValueError(f"Failed to fetch usage units: {error_msg}") from e
            else:
                raise

        except httpx.TimeoutException as e:
            raise ValueError(
                "Request timed out. The usage-unit-types API may be slow or unavailable."
            ) from e

    async def get_account_context(self) -> dict[str, Any]:
        """Get account context summary for the LLM."""
        if not self._account_info:
            if self.account_id and self.internal_client:
                self._account_info = await self._fetch_account_info()
            else:
                return {
                    "account_name": "Unknown",
                    "account_id": self.account_id or "Not configured",
                    "cost_centers": {},
                    "feature_flags": {},
                }

        metadata = await self.get_filters_metadata()

        cost_centers = {}
        for cc, types in metadata.items():
            filter_count = sum(len(filters) for filters in types.values())
            cost_centers[cc] = {"filter_count": filter_count}

        return {
            "account_name": self._account_info.get("name", "Unknown"),
            "account_id": self.account_id,
            "cost_centers": cost_centers,
            "feature_flags": self._account_info.get("featureFlags", {}),
        }

    # Context Discovery Methods

    async def get_dashboards(self) -> list[dict[str, Any]]:
        """
        Fetch all dashboards for the account.

        Returns:
            List of dashboard objects with name, widgets, dates, etc.
        """
        if not self.internal_client:
            raise ValueError("Internal API client not configured")

        # Fetch account info if needed
        if self.account_id and not self._account_info:
            import sys

            print(f"→ Fetching account info for {self.account_id}...", file=sys.stderr)
            try:
                self._account_info = await self._fetch_account_info()
            except Exception as e:
                print(f"✗ Failed to fetch account info: {e}", file=sys.stderr)

        headers = self._get_internal_headers()

        response = await self.internal_client.get(
            "/dashboard-service/dashboard",
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def get_widget(self, widget_id: str) -> dict[str, Any]:
        """
        Fetch a specific widget by ID.

        Args:
            widget_id: Widget ID to fetch

        Returns:
            Widget object with full configuration and query details
        """
        if not self.internal_client:
            raise ValueError("Internal API client not configured")

        headers = self._get_internal_headers()

        response = await self.internal_client.get(
            f"/dashboard-service/widget/{widget_id}",
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def get_views(self) -> list[dict[str, Any]]:
        """
        Fetch all views (saved queries) for the account.

        Returns:
            List of view objects with filters, groupBys, and query config
        """
        if not self.internal_client:
            raise ValueError("Internal API client not configured")

        # Fetch account info if needed
        if self.account_id and not self._account_info:
            import sys

            print(f"→ Fetching account info for {self.account_id}...", file=sys.stderr)
            try:
                self._account_info = await self._fetch_account_info()
            except Exception as e:
                print(f"✗ Failed to fetch account info: {e}", file=sys.stderr)

        headers = self._get_internal_headers()

        response = await self.internal_client.get(
            "/view-service/view",
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def get_data_explorers(self) -> list[dict[str, Any]]:
        """
        Fetch all data explorers for the account.

        Returns:
            List of data explorer objects with columns, filters, aggregations
        """
        if not self.internal_client or not self.account_id:
            raise ValueError("Internal API client and account_id required")

        # Fetch account info if needed
        if not self._account_info:
            import sys

            print(f"→ Fetching account info for {self.account_id}...", file=sys.stderr)
            try:
                self._account_info = await self._fetch_account_info()
            except Exception as e:
                print(f"✗ Failed to fetch account info: {e}", file=sys.stderr)

        headers = self._get_internal_headers()
        if self.internal_auth_mode == InternalAuthMode.AUTHORIZED_HEADERS:
            # Data explorer service requires sysAdmin role but scopes by accountId parameter
            headers["authorized-user-roles"] = "sysAdmin"

        response = await self.internal_client.get(
            "/data-explorer-service/data-explorer",
            headers=headers,
            params={"accountId": self.account_id},  # Required parameter for scoping
        )
        response.raise_for_status()
        return response.json()
