"""Feedback submission tool."""

import json
import sys
from datetime import datetime
from typing import Any


async def submit_feedback_impl(args: dict) -> dict:
    from ..server import feedback_log

    rating = args.get("rating")
    query_type = args.get("query_type")
    tools_used = args.get("tools_used", [])
    friction_points = args.get("friction_points", [])
    suggestion = args.get("suggestion")

    if not isinstance(rating, int) or rating < 1 or rating > 5:
        raise ValueError("rating must be an integer between 1 and 5")

    valid_types = [
        "cost_query",
        "comparison",
        "anomaly",
        "waste",
        "filter_discovery",
        "context",
        "other",
    ]
    if query_type not in valid_types:
        raise ValueError(f"query_type must be one of: {valid_types}")

    entry: dict[str, Any] = {
        "rating": rating,
        "query_type": query_type,
        "tools_used": tools_used,
        "friction_points": friction_points,
        "suggestion": suggestion,
        "timestamp": datetime.now().isoformat(),
    }

    feedback_log.append(entry)
    print(f"[feedback] {json.dumps(entry)}", file=sys.stderr)

    return {
        "status": "recorded",
        "total_feedback_count": len(feedback_log),
    }
