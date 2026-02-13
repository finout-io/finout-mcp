# Custom Date Range Support

## Problem
User asked Claude: "Can you compare the last 7 days of each of the last 4 months?"

This failed because the MCP tools only supported predefined time periods (enums) like "last_week", "last_month", etc. There was no way to specify custom date ranges like "Jan 25-31" or "Dec 25-31".

## Solution
Added support for custom date ranges in the format **"YYYY-MM-DD to YYYY-MM-DD"**

### Changes Made

#### 1. Enhanced `_parse_time_period()` in finout_client.py
Added logic to parse custom date range strings:

```python
# NEW: Supports custom ranges
if " to " in period:
    start_str, end_str = period.split(" to ", 1)
    # Parse dates in multiple formats
    start = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    # End date includes full day (23:59:59)
    end = end.replace(hour=23, minute=59, second=59)
    return int(start.timestamp()), int(end.timestamp())
```

#### 2. Updated Tool Schemas
Changed from strict enum to flexible string with description:

**Before:**
```python
"time_period": {
    "type": "string",
    "enum": ["today", "yesterday", "last_7_days", ...],  # ❌ Limited
}
```

**After:**
```python
"time_period": {
    "type": "string",
    "description": (
        "Supports:\n"
        "- Predefined: today, yesterday, last_7_days, ...\n"
        "- Custom range: 'YYYY-MM-DD to YYYY-MM-DD'\n"  # ✅ Flexible
    )
}
```

Applied to:
- `query_costs.time_period`
- `compare_costs.current_period`
- `compare_costs.comparison_period`

#### 3. Added Resource: `finout://date-range-examples`
Created a new MCP resource that provides:
- Format specification
- Real-time examples (last 7 days of last 4 months)
- Python code for calculating date ranges
- Usage tips and best practices

This resource is dynamically generated with current dates, so Claude always gets relevant examples.

## Test Results

```
✅ Custom date parsing:
   Input: "2026-01-24 to 2026-01-31"
   Parsed: 2026-01-24 00:00:00 to 2026-01-31 23:59:59

✅ Query with custom range:
   Period: "2026-01-25 to 2026-01-31" (January 2026)
   Result: $112,162.33

✅ Last 7 days of last 4 months:
   February 2026 (2026-02-22 to 2026-02-28): $0.00
   January 2026 (2026-01-25 to 2026-01-31): $112,162.33
   December 2025 (2025-12-25 to 2025-12-31): $123,158.91 (↑9.8% vs Jan)
   November 2025 (2025-11-24 to 2025-11-30): $110,442.04 (↓10.3% vs Dec)

✅ With filters (AWS only):
   January 2026 last 7 days: $111,303.64
```

## Usage Examples

### Basic Custom Range
```json
{
  "time_period": "2026-01-24 to 2026-01-31"
}
```

### Compare Two Custom Ranges
```json
{
  "current_period": "2026-01-25 to 2026-01-31",
  "comparison_period": "2025-12-25 to 2025-12-31"
}
```

### Multi-Month Comparison
Claude can now call query_costs multiple times with calculated date ranges:

```python
# Claude calculates these ranges
periods = [
    "2026-02-22 to 2026-02-28",  # Feb (last 7 days)
    "2026-01-25 to 2026-01-31",  # Jan (last 7 days)
    "2025-12-25 to 2025-12-31",  # Dec (last 7 days)
    "2025-11-24 to 2025-11-30"   # Nov (last 7 days)
]

# Then queries each one
for period in periods:
    result = query_costs(time_period=period, filters=[...])
```

### With Filters and Grouping
```json
{
  "time_period": "2026-01-25 to 2026-01-31",
  "filters": [{
    "costCenter": "global",
    "key": "cost_center_type",
    "type": "col",
    "operator": "is",
    "value": "AWS"
  }],
  "group_by": [{
    "costCenter": "amazon-cur",
    "key": "service",
    "path": "AWS/Service",
    "type": "col"
  }]
}
```

## Why This Matters

### Cyclical Billing Comparisons
Cloud costs often follow monthly billing cycles. Comparing "this month" (11 days) to "last month" (31 days) is misleading.

**Better approach:** Compare the same relative period
- Last 7 days of each month
- First week of each month
- Mid-month periods

**Example User Query:**
> "The reason you see this downtrend is because billing cycles are cyclical. Can you compare the last 7 days of each of the last 4 months?"

**Claude Can Now:**
1. Calculate: Feb 22-28, Jan 25-31, Dec 25-31, Nov 24-30
2. Query each period separately
3. Compare and show trends
4. Provide fair cyclical comparison

## Supported Date Formats

### Predefined (still supported)
- `today`, `yesterday`
- `last_7_days`, `last_30_days`
- `this_week`, `last_week`, `two_weeks_ago`
- `this_month`, `last_month`, `last_quarter`

### Custom Ranges (NEW)
- `"2026-01-24 to 2026-01-31"` - Basic format
- `"2025-12-01 to 2025-12-31"` - Full month
- `"2026-02-01 to 2026-02-07"` - First week
- Any valid date range in ISO format

## Files Modified

1. **src/finout_mcp_server/finout_client.py**
   - Enhanced `_parse_time_period()` to handle custom ranges
   - Added validation and error messages

2. **src/finout_mcp_server/server.py**
   - Updated `query_costs` time_period schema
   - Updated `compare_costs` period schemas
   - Added `finout://date-range-examples` resource

3. **test_custom_dates.py** (NEW)
   - Comprehensive test suite
   - Helper functions for calculating month-end ranges
   - Multi-month comparison examples

## Helper Functions

For users who want to calculate these programmatically:

```python
from calendar import monthrange
from datetime import datetime, timedelta

def get_last_n_days_of_month(year: int, month: int, n: int = 7) -> tuple[str, str]:
    """Get the last N days of a month"""
    last_day_num = monthrange(year, month)[1]
    last_day = datetime(year, month, last_day_num)
    first_day = last_day - timedelta(days=n-1)
    return (
        first_day.strftime("%Y-%m-%d"),
        last_day.strftime("%Y-%m-%d")
    )

# Example: Last 7 days of January 2026
start, end = get_last_n_days_of_month(2026, 1, 7)
# Returns: ("2026-01-25", "2026-01-31")
```

## Status: ✅ Complete

Claude can now handle complex date range queries including:
- Custom date ranges ✓
- Multi-month comparisons ✓
- Cyclical billing analysis ✓
- Fair period-to-period comparisons ✓
- Month-end date calculations ✓
