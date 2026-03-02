"""Filter validation helpers — value matching, metadata verification, auto-correction."""

import logging
from typing import Any

from .finout_client import FinoutClient

logger = logging.getLogger(__name__)


def _find_closest_values(target: str, known_values: list[str], top_n: int = 5) -> list[str]:
    """Find the closest matching values using substring and character overlap."""
    target_lower = target.lower()
    scored: list[tuple[float, str]] = []

    for val in known_values:
        val_lower = val.lower()
        score = 0.0

        # Exact case-insensitive match
        if val_lower == target_lower:
            score = 100.0
        # Target is substring of value
        elif target_lower in val_lower:
            score = 70.0 + (len(target_lower) / len(val_lower)) * 20
        # Value is substring of target
        elif val_lower in target_lower:
            score = 50.0 + (len(val_lower) / len(target_lower)) * 20
        else:
            # Character overlap ratio
            target_chars = set(target_lower)
            val_chars = set(val_lower)
            if target_chars and val_chars:
                overlap = len(target_chars & val_chars)
                score = (overlap / max(len(target_chars), len(val_chars))) * 40

        if score > 5:
            scored.append((score, val))

    scored.sort(key=lambda x: -x[0])
    return [val for _, val in scored[:top_n]]


async def _validate_filter_values(
    client: FinoutClient,
    filters: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate filter values against known values and auto-correct case mismatches.

    Returns:
        Tuple of (corrected_filters, warnings).
        Raises ValueError if a value is not found.
    """
    corrected = [dict(f) for f in filters]
    warnings: list[str] = []

    for i, f in enumerate(corrected):
        value = f.get("value")
        filter_key = f.get("key", "")
        cost_center = f.get("costCenter")
        filter_type = f.get("type")

        if value is None:
            continue

        # Fetch known values for this filter
        try:
            limit = 2000
            known_values = await client.get_filter_values(
                filter_key, cost_center, filter_type, limit=limit
            )
        except Exception:
            logger.debug("Could not fetch values for filter %s, skipping validation", filter_key)
            warnings.append(
                f"Filter '{filter_key}': value validation skipped (could not fetch known values). "
                f"The value '{value}' was NOT verified."
            )
            continue

        if not known_values:
            continue

        # Build case-insensitive lookup
        lower_to_actual: dict[str, str] = {}
        for kv in known_values:
            kv_str = str(kv)
            lower_to_actual[kv_str.lower()] = kv_str

        values_to_check = value if isinstance(value, list) else [value]
        corrected_values: list[str] = []

        for v in values_to_check:
            v_str = str(v)
            if v_str in [str(kv) for kv in known_values]:
                # Exact match
                corrected_values.append(v_str)
            elif v_str.lower() in lower_to_actual:
                # Case mismatch - auto-correct
                actual = lower_to_actual[v_str.lower()]
                corrected_values.append(actual)
                warnings.append(
                    f"Filter '{filter_key}': auto-corrected '{v_str}' → '{actual}' (case mismatch)"
                )
            else:
                # Value not found
                suggestions = _find_closest_values(v_str, [str(kv) for kv in known_values])
                suggestion_text = ", ".join(suggestions) if suggestions else "none"
                raise ValueError(
                    f"Filter '{filter_key}': value '{v_str}' not found.\n"
                    f"Closest matches: {suggestion_text}\n\n"
                    f"Call get_filter_values(filter_key='{filter_key}', "
                    f"cost_center='{cost_center}', filter_type='{filter_type}') "
                    f"to see all valid values."
                )

        if isinstance(value, list):
            corrected[i]["value"] = corrected_values
        else:
            corrected[i]["value"] = corrected_values[0]

    return corrected, warnings


async def _validate_filter_metadata(
    client: FinoutClient,
    filters: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate filter key/type/path against known filter metadata and auto-correct mismatches.

    Returns:
        Tuple of (corrected_filters, warnings).
        Raises ValueError if a filter key is not found.
    """
    try:
        metadata = await client.get_filters_metadata()
    except Exception:
        logger.debug("Could not fetch filter metadata, skipping metadata validation")
        return filters, [
            "Filter metadata validation skipped (could not fetch filter registry). "
            "Filter type/path were NOT verified — results may be incorrect."
        ]

    # Build lookup: (costCenter, key) -> list of {type, path}
    known: dict[tuple[str, str], list[dict[str, str]]] = {}
    # Case-insensitive lookup for robust matching of model-provided keys
    known_lower: dict[tuple[str, str], list[dict[str, str]]] = {}
    # Also build key-only lookup for cross-costCenter suggestions
    key_index: dict[str, list[dict[str, str]]] = {}

    for cc, filter_types in metadata.items():
        if not isinstance(filter_types, dict):
            continue
        for ft, filter_list in filter_types.items():
            if not isinstance(filter_list, list):
                continue
            for f in filter_list:
                key = f.get("key", "")
                path = f.get("path", "")
                entry = {"costCenter": cc, "type": ft, "path": path, "key": key}
                known.setdefault((cc, key), []).append(entry)
                known_lower.setdefault((cc.lower(), key.lower()), []).append(entry)
                key_index.setdefault(key.lower(), []).append(entry)

    corrected = [dict(f) for f in filters]
    warnings: list[str] = []

    for i, f in enumerate(corrected):
        filter_key = f.get("key", "")
        cost_center = f.get("costCenter", "")
        filter_type = f.get("type", "")
        filter_path = f.get("path", "")

        # Check if exact (costCenter, key) exists
        matches = known.get((cost_center, filter_key))
        if not matches:
            # Fall back to case-insensitive lookup in the same cost center.
            matches = known_lower.get((cost_center.lower(), filter_key.lower()))

        if matches:
            # Key exists in this cost center — check type/path
            exact = [m for m in matches if m["type"] == filter_type and m["path"] == filter_path]
            if exact:
                continue  # Perfect match

            # Type or path is wrong
            if len(matches) == 1:
                # Unambiguous — auto-correct
                best = matches[0]
                old_type = filter_type
                old_path = filter_path
                corrected[i]["type"] = best["type"]
                corrected[i]["path"] = best["path"]

                parts = []
                if old_type != best["type"]:
                    parts.append(f"type '{old_type}' → '{best['type']}'")
                if old_path != best["path"]:
                    parts.append(f"path '{old_path}' → '{best['path']}'")
                warnings.append(
                    f"Filter '{filter_key}': auto-corrected {', '.join(parts)}. "
                    f"Always copy exact metadata from search_filters results."
                )
                continue

            # Ambiguous — multiple type/path candidates, fail with options
            options = [f"  type='{m['type']}', path='{m['path']}'" for m in matches]
            raise ValueError(
                f"Filter key '{filter_key}' in '{cost_center}' matches multiple filters:\n"
                + "\n".join(options)
                + "\n\n"
                f"Call search_filters('{filter_key}') and copy the exact filter object."
            )

        # Key not found in this cost center — check other cost centers
        lower_matches = key_index.get(filter_key.lower(), [])
        if lower_matches:
            # Found in other cost centers — show where it actually is
            options = [
                f"  costCenter='{m['costCenter']}', type='{m['type']}', path='{m['path']}'"
                for m in lower_matches[:5]
            ]
            raise ValueError(
                f"Filter key '{filter_key}' not found in cost center '{cost_center}'.\n"
                f"Found in:\n" + "\n".join(options) + "\n\n"
                f"Call search_filters('{filter_key}') to find the correct filter metadata."
            )

        # Key not found anywhere — suggest similar keys
        all_keys = list({entry["key"] for entries in key_index.values() for entry in entries})
        suggestions = _find_closest_values(filter_key, all_keys)
        if suggestions:
            raise ValueError(
                f"Filter key '{filter_key}' not found.\n"
                f"Similar filters: {', '.join(suggestions)}\n\n"
                f"Call search_filters('{filter_key}') to find the correct filter."
            )
        raise ValueError(
            f"Filter key '{filter_key}' not found.\n"
            f"Call search_filters to discover available filters."
        )

    return corrected, warnings
