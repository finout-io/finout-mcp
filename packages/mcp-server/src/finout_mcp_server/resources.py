"""MCP resource definitions — static guides and dynamic data resources."""

import json
from datetime import datetime, timedelta

from mcp.types import AnyUrl, Resource


async def list_resources() -> list[Resource]:
    """List available resources"""
    return [
        Resource(
            uri=AnyUrl("finout://how-to-query"),
            name="How to Query Costs",
            description="Guide for building cost queries from natural language questions",
            mimeType="text/plain",
        ),
        Resource(
            uri=AnyUrl("finout://date-range-examples"),
            name="Custom Date Range Examples",
            description="Examples and formulas for calculating custom date ranges (e.g., last 7 days of each month)",
            mimeType="text/plain",
        ),
        Resource(
            uri=AnyUrl("finout://anomalies/active"),
            name="Active Anomalies",
            description="Currently active cost anomalies (last 7 days)",
            mimeType="application/json",
        ),
        Resource(
            uri=AnyUrl("finout://cost-centers"),
            name="Cost Centers",
            description="Available cost centers and cloud providers",
            mimeType="application/json",
        ),
    ]


async def read_resource(uri: str) -> str:
    """Read a resource by URI"""
    from .server import get_client

    try:
        finout_client = get_client()
    except RuntimeError:
        return json.dumps({"error": "Client not initialized"})

    try:
        if uri == "finout://how-to-query":
            return """# How to Query Finout Costs

## Workflow for Natural Language Cost Questions

When the user asks a cost question like "What was my EC2 cost last month?":

1. **Identify the entities** in the question:
   - Services: "EC2", "S3", "Lambda", "RDS", etc.
   - Regions: "us-east-1", "eu-west-1", etc.
   - Environments: "production", "staging", etc.
   - Resources: "pod", "namespace", "instance", etc.
   - Time period: "last month", "this week", "yesterday", etc.

2. **Search for relevant filters** using search_filters:
   - For "EC2": search_filters("service")
   - For "us-east-1": search_filters("region")
   - For "production": search_filters("environment")
   - For "pod": search_filters("pod")

3. **Build the query** with query_costs:
   - Use filters parameter with discovered filter keys
   - Set appropriate time_period
   - Add group_by if user wants breakdown

4. **Return the answer** in natural language

## Available Cost Centers
- aws: AWS cloud costs
- gcp: Google Cloud costs
- azure: Azure costs
- k8s: Kubernetes costs
- datadog: Datadog monitoring costs
- snowflake: Snowflake data warehouse costs

## Example Mappings

User Question → Filters:
- "EC2 costs" → search_filters("service") → {key: "service", value: ["ec2"]}
- "in us-east-1" → search_filters("region") → {key: "region", value: ["us-east-1"]}
- "production environment" → search_filters("environment") → {key: "environment", value: ["production"]}
- "by namespace" → search_filters("namespace") → group_by=["namespace"]
- "pods in production" → search_filters("pod") + search_filters("namespace")

## Key Principle
NEVER use list_available_filters unless specifically asked "what filters are available?"
ALWAYS use search_filters to find specific filters based on the user's question.
"""

        elif uri == "finout://date-range-examples":
            from calendar import monthrange

            now = datetime.now()
            current_year = now.year
            current_month = now.month

            # Calculate examples for last 4 months
            examples = []
            for i in range(4):
                # Calculate month
                month = current_month - i
                year = current_year
                while month <= 0:
                    month += 12
                    year -= 1

                # Get last 7 days
                last_day_num = monthrange(year, month)[1]
                last_day = datetime(year, month, last_day_num)
                first_day = last_day - timedelta(days=6)

                month_name = last_day.strftime("%B %Y")
                examples.append(
                    {
                        "month": month_name,
                        "date_range": f"{first_day.strftime('%Y-%m-%d')} to {last_day.strftime('%Y-%m-%d')}",
                        "description": f"Last 7 days of {month_name}",
                    }
                )

            return f"""# Custom Date Range Examples

## Overview
The query_costs and compare_costs tools now support custom date ranges in addition to predefined periods.

## Format
Custom date ranges use the format: **"YYYY-MM-DD to YYYY-MM-DD"**

Examples:
- "2026-01-24 to 2026-01-31" (last 7 days of January)
- "2025-12-01 to 2025-12-31" (all of December)
- "2026-02-01 to 2026-02-07" (first week of February)

## Predefined Periods Still Available
- today, yesterday
- last_7_days, last_30_days
- this_week, last_week, two_weeks_ago
- this_month, last_month, last_quarter

## Common Use Cases

### Last 7 Days of Each Month (for cyclical comparisons)
Today is {now.strftime("%Y-%m-%d")}

{chr(10).join([f"- {ex['month']}: **'{ex['date_range']}'**" for ex in examples])}

### Python Formula for Last 7 Days of a Month
```python
from calendar import monthrange
from datetime import datetime, timedelta

def get_last_7_days(year, month):
    last_day_num = monthrange(year, month)[1]
    last_day = datetime(year, month, last_day_num)
    first_day = last_day - timedelta(days=6)
    return f"{{first_day.strftime('%Y-%m-%d')}} to {{last_day.strftime('%Y-%m-%d')}}"
```

### How to Use with query_costs

**Single Month:**
```json
{{
  "time_period": "2026-01-25 to 2026-01-31",
  "filters": [...]
}}
```

**Compare Multiple Months:**
Call query_costs multiple times with different date ranges, then compare results:

```python
# Query each period
jan_costs = query_costs(time_period="2026-01-25 to 2026-01-31", ...)
dec_costs = query_costs(time_period="2025-12-25 to 2025-12-31", ...)
nov_costs = query_costs(time_period="2025-11-24 to 2025-11-30", ...)

# Compare and analyze trends
```

## Why Use Custom Ranges?

**Cyclical Billing Patterns:**
Many cloud costs follow monthly billing cycles. Comparing "last month" to "this month" can be misleading if you're mid-month. Instead, compare the same relative period (e.g., last 7 days) of each month for fairer comparison.

**Example:**
"Compare last 7 days of each of the last 4 months" gives you:
- Same number of days in each period
- Same relative position in billing cycle
- Better trend visibility

## Tips

1. **Always use YYYY-MM-DD format** (ISO 8601)
2. **End date is inclusive** (includes 23:59:59 of that day)
3. **Calculate dates programmatically** for complex queries
4. **Use Python's calendar.monthrange()** to get last day of month
"""

        elif uri == "finout://anomalies/active":
            try:
                anomalies = await finout_client.get_anomalies(time_period="last_7_days")
                return json.dumps(
                    {"active_anomalies": anomalies, "count": len(anomalies)}, indent=2
                )
            except NotImplementedError as e:
                return json.dumps(
                    {
                        "error": "Anomalies API not yet available",
                        "message": str(e),
                        "active_anomalies": [],
                        "count": 0,
                    },
                    indent=2,
                )

        elif uri == "finout://cost-centers":
            # Return static list of supported cost centers
            return json.dumps(
                {
                    "cost_centers": [
                        {"name": "AWS", "type": "cloud_provider"},
                        {"name": "GCP", "type": "cloud_provider"},
                        {"name": "Azure", "type": "cloud_provider"},
                        {"name": "Kubernetes", "type": "container_platform"},
                        {"name": "Datadog", "type": "saas"},
                        {"name": "Snowflake", "type": "saas"},
                    ]
                },
                indent=2,
            )

        else:
            return json.dumps({"error": f"Unknown resource: {uri}"})

    except Exception as e:
        return json.dumps({"error": str(e)})
