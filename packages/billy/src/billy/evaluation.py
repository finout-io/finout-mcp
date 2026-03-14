"""Langfuse evaluation dataset seeder and experiment runner for Billy."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

from langfuse.experiment import Evaluation

DATASET_NAME = "finout-eval"
REPO_ROOT = Path(__file__).resolve().parents[4]
CASES_PATH = REPO_ROOT / "evals" / "cases.json"
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "tool_correctness": 0.9,
    "tool_orchestration": 0.8,
    "tool_args": 0.8,
    "no_fabrication": 1.0,
}
DEFAULT_FAILURE_REPORT_LIMIT = 10
IGNORED_TOOLS = {"submit_feedback"}
ALLOWED_POST_TERMINAL_HELPERS = {"render_chart"}
DEFAULT_SETUP_TOOLS = {"search_filters", "get_filter_values", "get_usage_unit_types", "get_account_context"}
JUDGE_METRIC_KEYS = (
    "answers_question",
    "states_key_result",
    "grounded_in_tool_output",
    "directness",
    "actionability",
    "interaction_quality",
    "response_quality",
)


def build_judge_output_payload(
    *,
    response_text: str,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the compact interaction payload used by the LLM judge."""
    tool_trace = [
        {
            "index": idx,
            "name": tc.get("name"),
            "input": tc.get("input", {}),
            "output_summary": _summarize_for_judge(tc.get("output")),
            "error": bool(tc.get("error", False)),
        }
        for idx, tc in enumerate(tool_calls)
        if isinstance(tc, dict) and tc.get("name")
    ]
    return {
        "response": response_text or "",
        "tool_names": [entry["name"] for entry in tool_trace],
        "tool_trace": tool_trace,
    }


def judge_live_interaction(
    *,
    question: str,
    response_text: str,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the LLM judge against a completed Billy interaction."""
    output = build_judge_output_payload(
        response_text=response_text,
        tool_calls=tool_calls,
    )
    return _judge_interaction(output, {}, question)


def load_eval_cases(suite: str = "langfuse") -> list[dict[str, Any]]:
    raw_cases = json.loads(CASES_PATH.read_text())
    cases = [
        case for case in raw_cases if suite in case.get("suites", [])
    ]

    return [
        {
            "id": case["id"],
            "description": case["description"],
            "input": {"message": case["prompt"]},
            "expected": case.get("expected", {}),
            "tags": case.get("tags", []),
        }
        for case in cases
    ]


def _get_or_create_dataset(lf: Any):
    try:
        return lf.get_dataset(DATASET_NAME)
    except Exception:
        return lf.create_dataset(
            name=DATASET_NAME,
            description="Billy regression cases loaded from evals/cases.json",
        )


def _get_langfuse():
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        print("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must both be set", file=sys.stderr)
        sys.exit(1)
    from langfuse import Langfuse

    return Langfuse()


def seed_dataset() -> None:
    lf = _get_langfuse()
    _get_or_create_dataset(lf)
    items = load_eval_cases("langfuse")
    for idx, item in enumerate(items):
        lf.create_dataset_item(
            dataset_name=DATASET_NAME,
            input=item["input"],
            expected_output=item["expected"],
            metadata={
                "index": idx,
                "case_id": item["id"],
                "description": item["description"],
                "tags": item["tags"],
            },
        )
    lf.flush()
    print(f"Seeded {len(items)} items into '{DATASET_NAME}'")


# ---------------------------------------------------------------------------
# Task: run a single eval item through the Billy chat pipeline
# ---------------------------------------------------------------------------


async def _run_pipeline(message: str) -> dict[str, Any]:
    from .server import ChatRequest, MCPBridge, _run_chat_pipeline_inner, _tool_output_store

    account_id = os.getenv("FINOUT_ACCOUNT_ID", "eval")
    session_mcp = MCPBridge()
    await session_mcp.start(account_id)

    request = ChatRequest(
        message=message,
        model=os.getenv("EVAL_MODEL", "claude-sonnet-4-6"),
        conversation_history=[],
    )
    try:
        result = await _run_chat_pipeline_inner(request, session_mcp)
        request_id = result.get("request_id")
        if request_id and request_id in _tool_output_store:
            result["tool_call_details"] = _tool_output_store[request_id]["calls"]
        return result
    finally:
        await session_mcp.stop()


async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
    """Langfuse experiment task — runs one query through the chat pipeline."""
    input_data = item["input"] if isinstance(item, dict) else item.input
    result = await _run_pipeline(input_data["message"])
    tool_calls = result.get("tool_call_details") or result.get("tool_calls", [])
    tool_trace = [
        {
            "index": idx,
            "name": tc.get("name"),
            "input": tc.get("input", {}),
            "output_summary": _summarize_for_judge(tc.get("output")),
            "error": bool(tc.get("error", False)),
        }
        for idx, tc in enumerate(tool_calls)
        if isinstance(tc, dict) and tc.get("name")
    ]
    tool_inputs: Dict[str, Any] = {}
    for entry in tool_trace:
        tool_inputs.setdefault(entry["name"], entry["input"])
    return {
        "response": result.get("response", ""),
        "tool_names": [entry["name"] for entry in tool_trace],
        "tool_trace": tool_trace,
        # Map tool name → first input dict for backwards-compatible arg assertions
        "tool_inputs": tool_inputs,
    }


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------


def eval_tool_correctness(
    *,
    output: Any,
    expected_output: Any,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """Did the model call the expected tool(s)?"""
    expected = expected_output or {}
    expected_tools: List[str] = expected.get("required_tools") or expected.get("tools", [])
    if not expected_tools:
        score = 1.0
    else:
        called = set(output.get("tool_names", []))
        hits = sum(1 for t in expected_tools if t in called)
        score = hits / len(expected_tools)
    return Evaluation(name="tool_correctness", value=score)


def eval_tool_orchestration(
    *,
    output: Any,
    expected_output: Any,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """Does the run reach the right downstream tool and only use allowed setup tools first?"""
    expected = expected_output or {}
    tool_trace: List[Dict[str, Any]] = output.get("tool_trace", [])
    tool_names = [
        entry.get("name")
        for entry in tool_trace
        if entry.get("name") and entry.get("name") not in IGNORED_TOOLS
    ]
    if not tool_names:
        return Evaluation(name="tool_orchestration", value=0.0, comment="No tools called")

    terminal_tool = expected.get("terminal_tool")
    required_tools: List[str] = expected.get("required_tools") or expected.get("tools", [])
    allowed_prefix_tools = set(expected.get("allowed_prefix_tools", [])) | DEFAULT_SETUP_TOOLS

    mismatches: list[str] = []

    if terminal_tool:
        if terminal_tool not in tool_names:
            mismatches.append(f"terminal tool {terminal_tool} not called")
        else:
            terminal_index = max(
                idx for idx, name in enumerate(tool_names) if name == terminal_tool
            )
            post_terminal = tool_names[terminal_index + 1 :]
            disallowed_post_terminal = [
                name for name in post_terminal if name not in ALLOWED_POST_TERMINAL_HELPERS
            ]
            if disallowed_post_terminal:
                mismatches.append(
                    "disallowed tools after terminal tool: "
                    + ", ".join(disallowed_post_terminal)
                )

    if required_tools:
        missing = [tool for tool in required_tools if tool not in tool_names]
        if missing:
            mismatches.append(f"missing required tools: {', '.join(missing)}")

    if terminal_tool and terminal_tool in tool_names:
        terminal_index = next(idx for idx, name in enumerate(tool_names) if name == terminal_tool)
        disallowed_prefix = [
            name for name in tool_names[:terminal_index] if name not in allowed_prefix_tools
        ]
        if disallowed_prefix:
            mismatches.append(
                "disallowed tools before terminal tool: " + ", ".join(disallowed_prefix)
            )

    score = 1.0 if not mismatches else 0.0
    return Evaluation(
        name="tool_orchestration",
        value=score,
        comment="; ".join(mismatches) if mismatches else "Tool sequence is acceptable",
    )


def eval_tool_args(
    *,
    output: Any,
    expected_output: Any,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """Did the model call each expected tool with the right arguments?

    expected_output["args"] maps tool_name → {param: expected_value}.
    A value of None means the param must be ABSENT from the actual call.
    An empty dict ({}) means only presence of the tool is checked.
    """
    expected_args: Dict[str, Any] = (expected_output or {}).get("args", {})
    if not expected_args:
        return Evaluation(name="tool_args", value=1.0, comment="No arg expectations")

    mismatches = []

    for tool_name, expected in expected_args.items():
        actual = _latest_tool_input(output, tool_name)
        if actual is None:
            mismatches.append(f"{tool_name} not called")
            continue
        for param, exp_val in expected.items():
            mismatches.extend(
                _compare_expected_value(
                    actual=actual.get(param),
                    expected=exp_val,
                    path=f"{tool_name}.{param}",
                )
            )

    score = 1.0 if not mismatches else 0.0
    return Evaluation(
        name="tool_args",
        value=score,
        comment="; ".join(mismatches) if mismatches else "All args match",
    )


def eval_no_fabrication(
    *,
    output: Any,
    expected_output: Any = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """Did the model call at least one tool before responding?"""
    used_tools = len(output.get("tool_names", [])) > 0
    return Evaluation(
        name="no_fabrication",
        value=1.0 if used_tools else 0.0,
        comment="Called tools" if used_tools else "No tools called",
    )


def eval_final_text_present(
    *,
    output: Any,
    expected_output: Any = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """Did the assistant produce a non-empty final natural-language response?"""
    response_text = output.get("response", "") if isinstance(output, dict) else str(output)
    has_response = isinstance(response_text, str) and bool(response_text.strip())
    return Evaluation(
        name="final_text_present",
        value=1.0 if has_response else 0.0,
        comment="Final response text present" if has_response else "No final response text",
    )


def eval_chart_answer_present(
    *,
    output: Any,
    expected_output: Any = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """Did the assistant produce a chart answer via render_chart?

    Skipped (returns 1.0) when the eval case doesn't expect render_chart,
    so non-chart queries (filters, budget status, data explorers) don't
    create noise.
    """
    expected = expected_output or {}
    expected_tools = expected.get("tools", [])
    if expected_tools and "render_chart" not in expected_tools:
        return Evaluation(
            name="chart_answer_present",
            value=1.0,
            comment="Chart not expected for this case",
        )
    tool_names = output.get("tool_names", []) if isinstance(output, dict) else []
    has_chart = "render_chart" in tool_names
    return Evaluation(
        name="chart_answer_present",
        value=1.0 if has_chart else 0.0,
        comment="Chart answer present" if has_chart else "No chart answer",
    )


def eval_visible_answer_present(
    *,
    output: Any,
    expected_output: Any = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """Did the assistant produce any user-visible answer, via text or chart?"""
    response_text = output.get("response", "") if isinstance(output, dict) else str(output)
    has_text = isinstance(response_text, str) and bool(response_text.strip())
    tool_names = output.get("tool_names", []) if isinstance(output, dict) else []
    has_chart = "render_chart" in tool_names
    return Evaluation(
        name="visible_answer_present",
        value=1.0 if (has_text or has_chart) else 0.0,
        comment=(
            "Visible answer present"
            if (has_text or has_chart)
            else "No visible answer (neither text nor chart)"
        ),
    )


def _expects_text(expected: Dict[str, Any]) -> bool:
    return bool(expected.get("expects_text"))


def _expects_chart(expected: Dict[str, Any]) -> bool:
    return bool(expected.get("expects_chart"))


def _is_present_expectation(expected: Any) -> bool:
    return isinstance(expected, dict) and (
        expected == {} or expected.get("$present") is True
    )


def _is_regex_expectation(expected: Any) -> bool:
    return isinstance(expected, dict) and isinstance(expected.get("$regex"), str)


def _compare_expected_value(*, actual: Any, expected: Any, path: str) -> list[str]:
    if expected is None:
        if actual is not None:
            return [f"{path} should be absent, got {actual!r}"]
        return []

    if _is_present_expectation(expected):
        if actual is None:
            return [f"{path} missing"]
        return []

    if _is_regex_expectation(expected):
        pattern = expected["$regex"]
        if not isinstance(actual, str) or re.search(pattern, actual) is None:
            return [f"{path}={actual!r}, does not match /{pattern}/"]
        return []

    if isinstance(expected, list):
        actual_list = actual if isinstance(actual, list) else []
        mismatches: list[str] = []
        for item in expected:
            if isinstance(item, dict):
                if not any(
                    not _compare_expected_value(
                        actual=actual_item,
                        expected=item,
                        path=path,
                    )
                    for actual_item in actual_list
                ):
                    mismatches.append(f"{path} missing item {item!r}")
            elif item not in actual_list:
                mismatches.append(f"{path} missing value {item!r}")
        return mismatches

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}={actual!r}, want object {expected!r}"]
        mismatches: list[str] = []
        for key, value in expected.items():
            mismatches.extend(
                _compare_expected_value(
                    actual=actual.get(key),
                    expected=value,
                    path=f"{path}.{key}",
                )
            )
        return mismatches

    if actual != expected:
        return [f"{path}={actual!r}, want {expected!r}"]
    return []


def _latest_tool_input(output: Any, tool_name: str) -> Any:
    tool_trace: List[Dict[str, Any]] = output.get("tool_trace", []) if isinstance(output, dict) else []
    for entry in reversed(tool_trace):
        if entry.get("name") == tool_name:
            return entry.get("input", {})
    if isinstance(output, dict):
        return output.get("tool_inputs", {}).get(tool_name)
    return None


def _parse_judge_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidates = [stripped]

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced_match:
        candidates.append(fenced_match.group(1))

    object_match = re.search(r"(\{.*\})", stripped, re.DOTALL)
    if object_match:
        candidates.append(object_match.group(1))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue

    # Fallback: recover metric integers from loosely formatted text.
    recovered: dict[str, Any] = {}
    for key in JUDGE_METRIC_KEYS:
        match = re.search(rf'"?{re.escape(key)}"?\s*[:=]\s*([1-5])\b', stripped)
        if match:
            recovered[key] = int(match.group(1))

    reason_match = re.search(r'"?reason"?\s*[:=]\s*"([^"]+)"', stripped)
    if reason_match:
        recovered["reason"] = reason_match.group(1).strip()
    elif recovered:
        recovered["reason"] = "Recovered from non-JSON judge output"

    if recovered:
        return recovered

    raise json.JSONDecodeError("Could not parse judge payload", stripped, 0)


def _summarize_for_judge(value: Any, *, max_chars: int = 700) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except TypeError:
            text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _judge_input_payload(question: str, output: Any, expected: Dict[str, Any]) -> str:
    response_text = output.get("response", "") if isinstance(output, dict) else str(output)
    tool_trace = output.get("tool_trace", []) if isinstance(output, dict) else []
    rendered_chart = "render_chart" in (output.get("tool_names", []) if isinstance(output, dict) else [])

    trace_lines = []
    for entry in tool_trace:
        name = entry.get("name", "unknown")
        tool_input = _summarize_for_judge(entry.get("input", {}), max_chars=160)
        output_summary = _summarize_for_judge(entry.get("output_summary", ""), max_chars=260)
        suffix = f" output={output_summary}" if output_summary else ""
        trace_lines.append(f"- {name} input={tool_input}{suffix}")
    trace_summary = "\n".join(trace_lines) if trace_lines else "- none"

    return (
        "You are evaluating an AI assistant that helps cloud cost analysts.\n"
        "Judge both the final answer and whether the overall interaction made sense.\n\n"
        f"Question: {question}\n"
        f"Expected tools: {', '.join(expected.get('required_tools') or expected.get('tools', [])) or 'none'}\n"
        f"Expected terminal tool: {expected.get('terminal_tool', 'none')}\n"
        f"Expected text answer: {'yes' if _expects_text(expected) else 'no preference'}\n"
        f"Expected chart answer: {'yes' if _expects_chart(expected) else 'no preference'}\n"
        f"Response requirements: {', '.join(expected.get('response_checks', [])) or 'none'}\n"
        f"Chart rendered: {'yes' if rendered_chart else 'no'}\n"
        "Tool interaction trace:\n"
        f"{trace_summary}\n\n"
        f"Final assistant text:\n{response_text or '[none]'}\n\n"
        "Important rules:\n"
        "- Ignore submit_feedback completely.\n"
        "- Treat render_chart as a presentation helper, not a mistake.\n"
        "- Judge tool use by whether it was sensible for the user's request, not by whether it matched a rigid expected sequence.\n"
        "- If there is no final text, you may still give credit for a sensible chart-driven interaction, but penalize missing narration when the user likely needed explanation.\n\n"
        "Keep the reason to one short sentence.\n\n"
        "Return ONLY valid JSON with this schema:\n"
        '{"answers_question":1-5,"states_key_result":1-5,"grounded_in_tool_output":1-5,"directness":1-5,"actionability":1-5,"interaction_quality":1-5,"response_quality":1-5,"reason":"short reason"}'
    )


def _repair_judge_output(client: Any, raw_text: str) -> dict[str, Any]:
    repair_prompt = (
        "Convert the following evaluator output into valid JSON only.\n"
        "Preserve the scores if present. Use integers 1-5 for all score fields.\n"
        "Keep reason to one short sentence.\n"
        "Schema:\n"
        '{"answers_question":1-5,"states_key_result":1-5,"grounded_in_tool_output":1-5,"directness":1-5,"actionability":1-5,"interaction_quality":1-5,"response_quality":1-5,"reason":"short reason"}\n\n'
        f"Input:\n{raw_text}"
    )
    repair = client.messages.create(
        model=os.getenv("EVAL_JUDGE_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=180,
        messages=[{"role": "user", "content": repair_prompt}],
    )
    repaired_text = repair.content[0].text.strip() if repair.content else ""
    return _parse_judge_payload(repaired_text)


@lru_cache(maxsize=512)
def _judge_interaction_cached(
    question: str,
    output_json: str,
    expected_json: str,
) -> dict[str, Any]:
    from anthropic import Anthropic

    output = json.loads(output_json)
    expected = json.loads(expected_json)
    client = Anthropic()
    msg = client.messages.create(
        model=os.getenv("EVAL_JUDGE_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=320,
        messages=[{"role": "user", "content": _judge_input_payload(question, output, expected)}],
    )
    text = msg.content[0].text.strip() if msg.content else ""
    try:
        return _parse_judge_payload(text)
    except json.JSONDecodeError:
        return _repair_judge_output(client, text)


def _judge_interaction(output: Any, expected: Dict[str, Any], question: str) -> dict[str, Any]:
    try:
        return _judge_interaction_cached(
            question,
            json.dumps(output, sort_keys=True, ensure_ascii=True),
            json.dumps(expected, sort_keys=True, ensure_ascii=True),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"reason": "Judge output could not be parsed"}


def _judge_metric(
    *,
    metric_name: str,
    input: Any,
    output: Any,
    expected_output: Any = None,
) -> Evaluation:
    question = input["message"] if isinstance(input, dict) else str(input)
    expected = expected_output or {}
    judged = _judge_interaction(output, expected, question)
    raw_score = judged.get(metric_name)
    try:
        score = max(1, min(5, int(raw_score)))
    except (TypeError, ValueError):
        score = 3
    reason = str(judged.get("reason", "")).strip() or "No reason provided"
    return Evaluation(name=metric_name, value=float(score), comment=reason)


def eval_response_quality(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """LLM-as-judge: rate the final answer quality 1-5."""
    return _judge_metric(
        metric_name="response_quality",
        input=input,
        output=output,
        expected_output=expected_output,
    )


def eval_answers_question(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    return _judge_metric(
        metric_name="answers_question",
        input=input,
        output=output,
        expected_output=expected_output,
    )


def eval_states_key_result(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    return _judge_metric(
        metric_name="states_key_result",
        input=input,
        output=output,
        expected_output=expected_output,
    )


def eval_grounded_in_tool_output(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    return _judge_metric(
        metric_name="grounded_in_tool_output",
        input=input,
        output=output,
        expected_output=expected_output,
    )


def eval_directness(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    return _judge_metric(
        metric_name="directness",
        input=input,
        output=output,
        expected_output=expected_output,
    )


def eval_actionability(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    return _judge_metric(
        metric_name="actionability",
        input=input,
        output=output,
        expected_output=expected_output,
    )


def eval_interaction_quality(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """LLM-as-judge: did the overall interaction and tool usage make sense?"""
    return _judge_metric(
        metric_name="interaction_quality",
        input=input,
        output=output,
        expected_output=expected_output,
    )


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------


def _get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _iter_evaluation_entries(item_result: Any) -> Iterable[Any]:
    for field_name in ("evaluations", "evaluation_results", "evaluator_results", "scores", "results"):
        value = _get_attr_or_key(item_result, field_name)
        if isinstance(value, list):
            yield from value
            return
        if isinstance(value, dict):
            yield from value.values()
            return


def _extract_eval_name_value(entry: Any) -> tuple[str | None, float | None]:
    if entry is None:
        return None, None

    name = (
        _get_attr_or_key(entry, "name")
        or _get_attr_or_key(entry, "metric")
        or _get_attr_or_key(entry, "evaluator_name")
    )
    value = _get_attr_or_key(entry, "value")
    if value is None:
        value = _get_attr_or_key(entry, "score")
    try:
        numeric_value = float(value) if value is not None else None
    except (TypeError, ValueError):
        numeric_value = None
    return name, numeric_value


def _extract_eval_comment(entry: Any) -> str:
    comment = (
        _get_attr_or_key(entry, "comment")
        or _get_attr_or_key(entry, "reason")
        or _get_attr_or_key(entry, "message")
        or ""
    )
    return str(comment).strip()


def _summarize_metrics(result: Any) -> dict[str, dict[str, float]]:
    item_results = list(_get_attr_or_key(result, "item_results", []) or [])
    metric_values: dict[str, list[float]] = {}

    for item_result in item_results:
        for entry in _iter_evaluation_entries(item_result):
            name, value = _extract_eval_name_value(entry)
            if name is None or value is None:
                continue
            metric_values.setdefault(name, []).append(value)

    return {
        metric: {
            "mean": sum(values) / len(values),
            "count": float(len(values)),
            "min": min(values),
        }
        for metric, values in metric_values.items()
        if values
    }


def _format_threshold_status(metric: str, summary: dict[str, float], threshold: float) -> str:
    mean = summary["mean"]
    status = "PASS" if mean >= threshold else "FAIL"
    return (
        f"{metric}: {mean:.2f} "
        f"(threshold {threshold:.2f}, min {summary['min']:.2f}, n={int(summary['count'])}) "
        f"[{status}]"
    )


def _print_threshold_summary(result: Any, thresholds: Dict[str, float]) -> bool:
    metric_summary = _summarize_metrics(result)
    if not metric_summary:
        print("\nNo metric summary available from Langfuse result.")
        return False

    print("\nThreshold summary:")
    failed = False
    for metric, threshold in thresholds.items():
        summary = metric_summary.get(metric)
        if not summary:
            print(f"{metric}: missing metric output [FAIL]")
            failed = True
            continue
        line = _format_threshold_status(metric, summary, threshold)
        print(line)
        if summary["mean"] < threshold:
            failed = True

    return failed


def _normalize_item_record(item_result: Any, source_item: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    input_data = _get_attr_or_key(item_result, "input", None)
    expected_output = _get_attr_or_key(item_result, "expected_output", None)
    metadata = _get_attr_or_key(item_result, "metadata", None)
    output = _get_attr_or_key(item_result, "output", {}) or {}

    if source_item:
        input_data = input_data or source_item.get("input", {})
        expected_output = expected_output or source_item.get("expected_output", {})
        metadata = metadata or source_item.get("metadata", {})

    input_data = input_data or {}
    expected_output = expected_output or {}
    metadata = metadata or {}

    evaluations: dict[str, dict[str, Any]] = {}
    for entry in _iter_evaluation_entries(item_result):
        name, value = _extract_eval_name_value(entry)
        if name is None or value is None:
            continue
        evaluations[name] = {
            "value": value,
            "comment": _extract_eval_comment(entry),
        }

    return {
        "case_id": metadata.get("case_id") or _get_attr_or_key(item_result, "id") or "unknown",
        "description": metadata.get("description", ""),
        "tags": metadata.get("tags", []),
        "prompt": input_data.get("message") if isinstance(input_data, dict) else str(input_data),
        "expected_output": expected_output,
        "output": output,
        "evaluations": evaluations,
    }


def _print_failure_report(
    result: Any,
    thresholds: Dict[str, float],
    *,
    source_items: Optional[List[dict[str, Any]]] = None,
    limit: int = DEFAULT_FAILURE_REPORT_LIMIT,
) -> None:
    item_results = list(_get_attr_or_key(result, "item_results", []) or [])
    records = [
        _normalize_item_record(
            item,
            source_item=source_items[idx] if source_items and idx < len(source_items) else None,
        )
        for idx, item in enumerate(item_results)
    ]
    if not records:
        return

    print("\nWorst cases by metric:")
    for metric, threshold in thresholds.items():
        failures = []
        for record in records:
            evaluation = record["evaluations"].get(metric)
            if not evaluation:
                continue
            if evaluation["value"] < threshold:
                failures.append(
                    {
                        "case_id": record["case_id"],
                        "prompt": record["prompt"],
                        "value": evaluation["value"],
                        "comment": evaluation["comment"],
                        "tool_sequence": " -> ".join(
                            record["output"].get("tool_names", []) if isinstance(record["output"], dict) else []
                        ),
                        "tags": record["tags"],
                    }
                )
        failures.sort(key=lambda item: item["value"])
        if not failures:
            continue
        print(f"\n{metric} failures:")
        for failure in failures[:limit]:
            print(
                f"- {failure['case_id']}: score={failure['value']:.2f} tags={','.join(failure['tags']) or 'none'}"
            )
            print(f"  prompt: {failure['prompt']}")
            if failure["tool_sequence"]:
                print(f"  tools: {failure['tool_sequence']}")
            if failure["comment"]:
                print(f"  note: {failure['comment']}")

    print("\nFailure summary by tag:")
    tag_metric_counts: dict[str, dict[str, int]] = {}
    for metric, threshold in thresholds.items():
        for record in records:
            evaluation = record["evaluations"].get(metric)
            if not evaluation or evaluation["value"] >= threshold:
                continue
            tags = record["tags"] or ["untagged"]
            for tag in tags:
                tag_metric_counts.setdefault(tag, {})
                tag_metric_counts[tag][metric] = tag_metric_counts[tag].get(metric, 0) + 1

    if not tag_metric_counts:
        print("No threshold failures by tag.")
        return

    ranked_tags = sorted(
        tag_metric_counts.items(),
        key=lambda item: sum(item[1].values()),
        reverse=True,
    )
    for tag, counts in ranked_tags[:limit]:
        summary = ", ".join(f"{metric}={count}" for metric, count in sorted(counts.items()))
        print(f"- {tag}: {summary}")


def _print_communication_failures(
    result: Any,
    *,
    source_items: Optional[List[dict[str, Any]]] = None,
    limit: int = DEFAULT_FAILURE_REPORT_LIMIT,
) -> None:
    item_results = list(_get_attr_or_key(result, "item_results", []) or [])
    records = [
        _normalize_item_record(
            item,
            source_item=source_items[idx] if source_items and idx < len(source_items) else None,
        )
        for idx, item in enumerate(item_results)
    ]
    if not records:
        return

    watched_metrics = {
        "answers_question": 4.0,
        "states_key_result": 4.0,
        "directness": 4.0,
        "response_quality": 4.0,
        "visible_answer_present": 1.0,
    }
    failures = []
    for record in records:
        failed_metrics = []
        worst_value = 5.0
        for metric, threshold in watched_metrics.items():
            evaluation = record["evaluations"].get(metric)
            if not evaluation or evaluation["value"] >= threshold:
                continue
            failed_metrics.append(metric)
            worst_value = min(worst_value, evaluation["value"])
        if not failed_metrics:
            continue
        failures.append(
            {
                "case_id": record["case_id"],
                "prompt": record["prompt"],
                "tags": record["tags"],
                "tool_sequence": " -> ".join(
                    record["output"].get("tool_names", []) if isinstance(record["output"], dict) else []
                ),
                "failed_metrics": failed_metrics,
                "worst_value": worst_value,
                "reason": next(
                    (
                        record["evaluations"][metric]["comment"]
                        for metric in ("response_quality", "answers_question", "states_key_result", "directness")
                        if metric in record["evaluations"] and record["evaluations"][metric]["comment"]
                    ),
                    "",
                ),
            }
        )

    if not failures:
        return

    failures.sort(key=lambda item: (item["worst_value"], len(item["failed_metrics"])))
    print("\nTop Communication Failures:")
    for failure in failures[:limit]:
        print(
            f"- {failure['case_id']}: failed={','.join(failure['failed_metrics'])} "
            f"tags={','.join(failure['tags']) or 'none'}"
        )
        print(f"  prompt: {failure['prompt']}")
        if failure["tool_sequence"]:
            print(f"  tools: {failure['tool_sequence']}")
        if failure["reason"]:
            print(f"  note: {failure['reason']}")


def run_experiment(
    name: str,
    source: str = "local",
    *,
    enforce_thresholds: bool = False,
    report_limit: int = DEFAULT_FAILURE_REPORT_LIMIT,
    thresholds: Optional[Dict[str, float]] = None,
    verbose: bool = False,
) -> None:
    lf = _get_langfuse()
    if source == "dataset":
        dataset = lf.get_dataset(DATASET_NAME)
        data_list = list(dataset.items)
    else:
        data_list = [
            {
                "input": item["input"],
                "expected_output": item["expected"],
                "metadata": {
                    "case_id": item["id"],
                    "description": item["description"],
                    "tags": item["tags"],
                },
            }
            for item in load_eval_cases("langfuse")
        ]

    result = lf.run_experiment(
        name=DATASET_NAME,
        run_name=name,
        data=data_list,
        task=task,
        evaluators=[
            eval_tool_correctness,  # type: ignore[list-item]
            eval_tool_orchestration,  # type: ignore[list-item]
            eval_tool_args,  # type: ignore[list-item]
            eval_no_fabrication,
            eval_final_text_present,
            eval_chart_answer_present,
            eval_visible_answer_present,
            eval_answers_question,
            eval_states_key_result,
            eval_grounded_in_tool_output,
            eval_directness,
            eval_actionability,
            eval_interaction_quality,
            eval_response_quality,
        ],
    )

    print(
        f"\nExperiment '{name}' complete — {len(result.item_results)} items "
        f"(source={source})"
    )
    print("Check the Langfuse Datasets tab for scores.")
    thresholds = thresholds or DEFAULT_THRESHOLDS

    # ── Infrastructure metrics (enforced, failures always printed) ────────
    infra_thresholds = dict(thresholds)
    infra_thresholds.setdefault("visible_answer_present", 0.98)
    infra_thresholds.setdefault("final_text_present", 0.95)
    infra_thresholds.setdefault("chart_answer_present", 0.5)

    failed = _print_threshold_summary(result, infra_thresholds)
    _print_failure_report(
        result, infra_thresholds, source_items=data_list, limit=report_limit
    )

    # ── Quality metrics (informational, compact summary only) ─────────────
    quality_thresholds: Dict[str, float] = {
        "response_quality": 4.0,
        "answers_question": 4.0,
        "states_key_result": 4.0,
        "grounded_in_tool_output": 4.0,
        "directness": 4.0,
        "actionability": 4.0,
        "interaction_quality": 4.0,
    }
    metric_summary = _summarize_metrics(result)
    if metric_summary:
        print("\nQuality metrics (informational):")
        for metric, threshold in quality_thresholds.items():
            summary = metric_summary.get(metric)
            if not summary:
                continue
            print(_format_threshold_status(metric, summary, threshold))

    if verbose:
        _print_failure_report(
            result, quality_thresholds, source_items=data_list, limit=report_limit
        )
        _print_communication_failures(result, source_items=data_list, limit=report_limit)

    if failed and enforce_thresholds:
        print("\nThreshold check failed.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="billy.evaluation")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("seed", help="Seed the eval dataset in Langfuse")

    run_parser = sub.add_parser("run", help="Run an experiment")
    run_parser.add_argument("--name", required=True, help="Experiment run name")
    run_parser.add_argument(
        "--source",
        choices=["local", "dataset"],
        default="local",
        help="Use local evals/cases.json or a pre-seeded Langfuse dataset",
    )
    run_parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit non-zero if any default threshold is missed",
    )
    run_parser.add_argument(
        "--report-limit",
        type=int,
        default=DEFAULT_FAILURE_REPORT_LIMIT,
        help="How many failing cases/tags to print per metric in the local summary",
    )
    run_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full quality-metric failure details and communication failures",
    )

    args = parser.parse_args()
    if args.command == "seed":
        seed_dataset()
    elif args.command == "run":
        run_experiment(
            args.name,
            source=args.source,
            enforce_thresholds=args.enforce_thresholds,
            report_limit=args.report_limit,
            verbose=args.verbose,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
