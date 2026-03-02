"""Chart rendering — validation and pass-through of chart data."""


async def render_chart_impl(args: dict) -> dict:
    """Implementation of render_chart tool — validates and passes through chart data."""
    required = ["title", "chart_type", "categories", "series"]
    missing = [f for f in required if f not in args]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    valid_types = {"bar", "line", "pie", "column"}
    if args["chart_type"] not in valid_types:
        raise ValueError(f"chart_type must be one of: {sorted(valid_types)}")

    if not isinstance(args["categories"], list):
        raise ValueError("categories must be an array of strings")
    if len(args["categories"]) == 0:
        raise ValueError("categories must be a non-empty array")
    if not all(isinstance(c, str) and c.strip() for c in args["categories"]):
        raise ValueError("categories must contain non-empty strings")

    if not isinstance(args["series"], list) or len(args["series"]) == 0:
        raise ValueError("series must be a non-empty array")

    y_axes = args.get("y_axes")
    if y_axes is not None:
        if args["chart_type"] != "line":
            raise ValueError("y_axes is only supported for line charts")
        if not isinstance(y_axes, list) or len(y_axes) == 0:
            raise ValueError("y_axes must be a non-empty array when provided")
        for i, axis in enumerate(y_axes):
            if not isinstance(axis, dict):
                raise ValueError(f"y_axes[{i}] must be an object")
            label = axis.get("label")
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"y_axes[{i}].label must be a non-empty string")
            if "opposite" in axis and not isinstance(axis["opposite"], bool):
                raise ValueError(f"y_axes[{i}].opposite must be a boolean")
            if "min" in axis and not isinstance(axis["min"], int | float):
                raise ValueError(f"y_axes[{i}].min must be a number")
            if "max" in axis and not isinstance(axis["max"], int | float):
                raise ValueError(f"y_axes[{i}].max must be a number")

    colors = args.get("colors")
    if colors is not None:
        if not isinstance(colors, list) or len(colors) == 0:
            raise ValueError("colors must be a non-empty array when provided")
        for i, color in enumerate(colors):
            if not isinstance(color, str) or not color.strip():
                raise ValueError(f"colors[{i}] must be a non-empty string")

    category_count = len(args["categories"])
    for i, s in enumerate(args["series"]):
        if not isinstance(s, dict) or "name" not in s or "data" not in s:
            raise ValueError(f"series[{i}] must have 'name' and 'data' fields")
        if not isinstance(s["name"], str) or not s["name"].strip():
            raise ValueError(f"series[{i}].name must be a non-empty string")
        if not isinstance(s["data"], list):
            raise ValueError(f"series[{i}].data must be an array of numbers")
        if len(s["data"]) != category_count:
            raise ValueError(
                f"series[{i}].data length ({len(s['data'])}) must match categories length ({category_count})"
            )
        for j, v in enumerate(s["data"]):
            if not isinstance(v, int | float):
                raise ValueError(f"series[{i}].data[{j}] must be a number")
        if "color" in s and (not isinstance(s["color"], str) or not s["color"].strip()):
            raise ValueError(f"series[{i}].color must be a non-empty string")
        if "y_axis" in s:
            if args["chart_type"] != "line":
                raise ValueError(f"series[{i}].y_axis is only supported for line charts")
            if not isinstance(s["y_axis"], int) or s["y_axis"] < 0:
                raise ValueError(f"series[{i}].y_axis must be a non-negative integer")
            if not isinstance(y_axes, list):
                raise ValueError(
                    f"series[{i}].y_axis requires y_axes to be defined for line charts"
                )
            if s["y_axis"] >= len(y_axes):
                raise ValueError(
                    f"series[{i}].y_axis ({s['y_axis']}) out of range for y_axes "
                    f"(len={len(y_axes)})"
                )

    if args["chart_type"] == "pie" and len(args["series"]) != 1:
        raise ValueError("pie charts must have exactly one series")

    return {
        "title": args["title"],
        "chart_type": args["chart_type"],
        "categories": args["categories"],
        "series": args["series"],
        "colors": colors,
        "y_axes": y_axes,
        "x_label": args.get("x_label"),
        "y_label": args.get("y_label", "Cost ($)"),
    }
