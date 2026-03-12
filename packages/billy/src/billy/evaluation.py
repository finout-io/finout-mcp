"""Langfuse evaluation dataset seeder and experiment runner for Billy."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from langfuse.experiment import Evaluation

DATASET_NAME = "finout-eval"
REPO_ROOT = Path(__file__).resolve().parents[4]
CASES_PATH = REPO_ROOT / "evals" / "cases.json"


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
    from .server import ChatRequest, MCPBridge, _run_chat_pipeline_inner

    account_id = os.getenv("FINOUT_ACCOUNT_ID", "eval")
    session_mcp = MCPBridge()
    await session_mcp.start(account_id)

    request = ChatRequest(
        message=message,
        model=os.getenv("EVAL_MODEL", "claude-sonnet-4-6"),
        conversation_history=[],
    )
    try:
        return await _run_chat_pipeline_inner(request, session_mcp)
    finally:
        await session_mcp.stop()


async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
    """Langfuse experiment task — runs one query through the chat pipeline."""
    input_data = item["input"] if isinstance(item, dict) else item.input
    result = await _run_pipeline(input_data["message"])
    tool_calls = result.get("tool_calls", [])
    return {
        "response": result.get("response", ""),
        "tool_names": [tc["name"] for tc in tool_calls],
        # Map tool name → first input dict for arg-level assertions
        "tool_inputs": {tc["name"]: tc["input"] for tc in tool_calls},
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
    expected_tools: List[str] = (expected_output or {}).get("tools", [])
    if not expected_tools:
        score = 1.0
    else:
        called = set(output.get("tool_names", []))
        hits = sum(1 for t in expected_tools if t in called)
        score = hits / len(expected_tools)
    return Evaluation(name="tool_correctness", value=score)


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

    tool_inputs: Dict[str, Any] = output.get("tool_inputs", {})
    mismatches = []

    for tool_name, expected in expected_args.items():
        actual = tool_inputs.get(tool_name)
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


def eval_response_quality(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Evaluation:
    """LLM-as-judge: rate the response 1-5 for a cloud cost analyst."""
    from anthropic import Anthropic

    question = input["message"] if isinstance(input, dict) else input
    response_text = (
        output.get("response", "") if isinstance(output, dict) else str(output)
    )
    tool_names = output.get("tool_names", []) if isinstance(output, dict) else []

    client = Anthropic()
    judge_prompt = (
        "You are evaluating an AI assistant that helps cloud cost analysts.\n"
        "The user asked a question and the assistant replied (after calling tools).\n\n"
        f"Question: {question}\n"
        f"Tools called: {', '.join(tool_names) or 'none'}\n"
        f"Response:\n{response_text}\n\n"
        "Rate the response from 1 to 5:\n"
        "1 = Unusable (wrong, irrelevant, or empty)\n"
        "2 = Poor (partially relevant but missing key info)\n"
        "3 = Acceptable (answers the question but could be clearer)\n"
        "4 = Good (clear, accurate, actionable)\n"
        "5 = Excellent (insightful, well-structured, goes above expectations)\n\n"
        "Reply with ONLY a single digit (1-5), nothing else."
    )
    msg = client.messages.create(
        model=os.getenv("EVAL_JUDGE_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=4,
        messages=[{"role": "user", "content": judge_prompt}],
    )
    text = msg.content[0].text.strip() if msg.content else ""
    try:
        score = int(text[0])
        score = max(1, min(5, score))
    except (ValueError, IndexError):
        score = 3
    return Evaluation(name="response_quality", value=float(score))


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------


def run_experiment(name: str, source: str = "local") -> None:
    lf = _get_langfuse()
    if source == "dataset":
        dataset = lf.get_dataset(DATASET_NAME)
        data: Iterable[Any] = dataset.items
    else:
        data = [
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
        data=list(data),
        task=task,
        evaluators=[
            eval_tool_correctness,  # type: ignore[list-item]
            eval_tool_args,  # type: ignore[list-item]
            eval_no_fabrication,
            eval_response_quality,
        ],
    )

    print(
        f"\nExperiment '{name}' complete — {len(result.item_results)} items "
        f"(source={source})"
    )
    print("Check the Langfuse Datasets tab for scores.")


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

    args = parser.parse_args()
    if args.command == "seed":
        seed_dataset()
    elif args.command == "run":
        run_experiment(args.name, source=args.source)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
