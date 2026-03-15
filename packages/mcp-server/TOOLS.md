# Finout MCP Server — Tool Reference

Reference documentation for the Finout MCP server tools that provide access to your cloud cost data.

## Overview

The Finout MCP server exposes tools that AI assistants (Claude, etc.) use to query and analyze your cloud costs. Tools handle data retrieval and filtering; the AI model handles analysis and presentation.

## Authentication

Authenticate using your Finout API credentials:

| Header | Description |
|--------|-------------|
| `x-finout-client-id` | Your Finout Client ID |
| `x-finout-secret-key` | Your Finout Secret Key |

Credentials are scoped to your account and control which cost data is accessible.

---

## Tools Overview

| Tool | Capability | Description |
|------|-----------|-------------|
| [query_costs](#query_costs) | Cost & usage queries | Query cloud costs with filters, grouping, and optional usage data |
| [compare_costs](#compare_costs) | Period comparison | Compare costs between two time periods |
| [get_anomalies](#get_anomalies) | Anomaly detection | Retrieve detected cost spikes and anomalies |
| [get_financial_plans](#get_financial_plans) | Budget & forecast | Get financial plans with budget vs. forecast data |
| [get_waste_recommendations](#get_waste_recommendations) | Cost optimization | Get CostGuard waste detection and rightsizing recommendations |
| [search_filters](#search_filters) | Filter discovery | Search for filter metadata before querying costs |
| [get_filter_values](#get_filter_values) | Filter values | Get available values for a specific filter |
| [list_available_filters](#list_available_filters) | Filter catalog | List all available filters organized by cost center |
| [get_usage_unit_types](#get_usage_unit_types) | Usage discovery | Discover valid usage units before a usage query |

---

## query_costs

**Purpose**

Query cloud costs and usage data with flexible filters and grouping. Supports all major cloud providers (AWS, Azure, GCP) and Kubernetes. Returns time-series data broken down by the requested dimensions.

**Typical workflow**

1. Call `search_filters` to find filter metadata for the dimension you want
2. Copy the full filter object (`costCenter`, `key`, `path`, `type`) from the result
3. Call `query_costs` with those filters

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `time_period` | Yes | Time period to analyze (default: `last_30_days`). See [Time Periods](#time-periods). |
| `filters` | No | Filters to narrow results. Each filter must include `costCenter`, `key`, `path`, `type`, `operator`, and `value` — copy these from `search_filters` results. |
| `group_by` | No | Dimensions to group results by. Each entry requires `costCenter`, `key`, `path`, and `type`. |
| `x_axis_group_by` | No | Override auto-selected time granularity. Values: `daily`, `weekly`, `monthly`, `quarterly`. Omit to let the server choose. |
| `usage_configuration` | No | When provided, returns usage data alongside cost. Requires `usageType`, `costCenter`, and `units`. Call `get_usage_unit_types` first to discover valid units. |

**Filter operators**

| Operator | Behavior |
|----------|----------|
| `is` | Exact match (single value) |
| `oneOf` | Matches any of the provided values (array) |
| `not` | Excludes the value |
| `notOneOf` | Excludes any of the provided values |

**Examples**

Filter by AWS service:
```json
{
  "costCenter": "amazon-cur",
  "key": "finrichment_product_name",
  "path": "AMAZON-CUR/Product",
  "type": "col",
  "operator": "is",
  "value": "ec2"
}
```

Filter by Kubernetes deployment:
```json
{
  "costCenter": "kubernetes",
  "key": "deployment",
  "path": "Kubernetes/Resources/deployment",
  "type": "namespace_object",
  "operator": "oneOf",
  "value": ["api-server", "worker"]
}
```

Filter by custom tag:
```json
{
  "costCenter": "amazon-cur",
  "key": "environment",
  "path": "AWS/Tags/environment",
  "type": "tag",
  "operator": "is",
  "value": "production"
}
```

---

## compare_costs

**Purpose**

Compare cloud costs between two time periods. Use this when analyzing cost changes, trends, or investigating why spending increased or decreased.

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `current_period` | Yes | The recent period to compare. See [Time Periods](#time-periods). |
| `comparison_period` | Yes | The baseline period to compare against. See [Time Periods](#time-periods). |
| `filters` | No | Filters applied to both periods. Same format as `query_costs`. |
| `group_by` | No | Dimensions to group the comparison by. Same format as `query_costs`. |

---

## get_anomalies

**Purpose**

Retrieve cost anomalies and spikes detected by Finout. Use this when investigating unexpected charges, sudden cost increases, or irregular spending patterns.

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `time_period` | Yes | Period to check. Values: `today`, `yesterday`, `last_7_days`, `last_30_days`. Default: `last_7_days`. |
| `severity` | No | Filter by severity. Values: `high`, `medium`, `low`. |

---

## get_financial_plans

**Purpose**

Get financial plans with budget, actual cost, run rate, and forecast. Without `name`, lists all plans with their date ranges and status (active/future/past). With `name`, fetches detailed budget vs actual data for one plan.

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `name` | No | Plan name to look up (partial, case-insensitive). Omit to list all plans. |
| `period` | No | Month in `YYYY-M` format (e.g. `2026-4`). Auto-selects the best period if omitted. |

---

## get_waste_recommendations

**Purpose**

Get CostGuard waste detection and optimization recommendations. Identifies idle resources, over-provisioned instances, and commitment coverage gaps.

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `scan_type` | No | Type of waste to find. Values: `idle` (unused resources), `rightsizing` (over-provisioned), `commitment` (RI/SP gaps). |
| `service` | No | Limit to a specific service. Values: `ec2`, `rds`, `ebs`, `lambda`, `s3`. |
| `min_saving` | No | Minimum monthly savings threshold in dollars. Only returns recommendations above this amount. |

---

## search_filters

**Purpose**

Search for filter metadata by name. This is the required first step before calling `query_costs` or `compare_costs` — it returns the `costCenter`, `key`, `path`, and `type` fields that those tools require.

Searches across columns (service, region, account), custom tags (environment, team), and Kubernetes resources (deployment, pod, namespace).

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `query` | Yes | Search term (case-insensitive, partial matching). Examples: `service`, `environment`, `pod`, `team`. |
| `cost_center` | No | Limit results to a specific cost center. |

Returns up to 50 matches sorted by relevance.

---

## get_filter_values

**Purpose**

Retrieve the available values for a specific filter. Use this after `search_filters` to verify exact values or when the user asks what options exist for a dimension (e.g., "what services do we use?", "what environments exist?").

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `filter_key` | Yes | The filter key to look up (e.g., `service`, `region`, `deployment`). |
| `cost_center` | No | Cost center the filter belongs to (case-insensitive). |
| `filter_type` | No | Filter type — must match the exact `type` value from `search_filters`. Common values: `col`, `tag`, `namespace_object`. |
| `limit` | No | Maximum values to return. Range: 1–500. Default: 100. Use 300–500 when searching for a specific substring match. |

---

## list_available_filters

**Purpose**

List all available cost filters organized by cost center. Use only when the user explicitly asks to see all available filters. For targeted lookups, prefer `search_filters` — this endpoint returns a large response.

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `cost_center` | No | Limit results to a specific cost center (e.g., `amazon-cur`, `GCP`, `kubernetes`). Returns all cost centers if omitted. |

---

## get_usage_unit_types

**Purpose**

Discover the available usage unit types for a cost center (AWS, Azure, GCP, etc.). Always call this before passing `usage_configuration` to `query_costs` — without it you won't know which unit strings are valid.

**Workflow:** `get_usage_unit_types` → `query_costs` with `usage_configuration`

**Parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `time_period` | No | Time period for discovery. Default: `last_30_days`. |
| `filters` | No | Filters to narrow down to a specific cost center (e.g., filter by `cost_center_type = AWS`). Same format as `query_costs` filters. |

---

## Parameter Reference

### Time Periods

| Value | Description |
|-------|-------------|
| `today` | Current day |
| `yesterday` | Previous day |
| `last_7_days` | Rolling 7 days |
| `this_week` | Current calendar week |
| `last_week` | Previous calendar week |
| `two_weeks_ago` | The week before last |
| `last_30_days` | Rolling 30 days (default) |
| `this_month` | Current calendar month |
| `last_month` | Previous calendar month |
| `last_quarter` | Previous calendar quarter |
| `YYYY-MM-DD to YYYY-MM-DD` | Custom date range (e.g., `2026-01-01 to 2026-01-31`) |

### Cost Types

| Value | Description |
|-------|-------------|
| `netAmortizedCost` | Net cost after discounts, with upfront fees spread over the term (default) |
| `blendedCost` | Blended rate across all usage in the account |
| `unblendedCost` | On-demand cost without reserved instance blending |
| `amortizedCost` | Upfront reservation fees amortized over the commitment period |

### Filter Types

| Value | Description |
|-------|-------------|
| `col` | Standard column dimensions (service, region, account, etc.) |
| `tag` | Custom resource tags (environment, team, application, etc.) |
| `resource` | Resource-level dimensions (RDS instances, SQS queues, ECR repos) |
| `namespace_object` | Kubernetes objects (deployment, pod, service, namespace) |
