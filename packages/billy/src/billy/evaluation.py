"""Langfuse evaluation dataset seeder and experiment runner for Billy."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

DATASET_NAME = "finout-eval"

EVAL_ITEMS: list[dict[str, Any]] = [
    {
        "input": {"message": "What were my top 5 costs last month?"},
        "expected": {"tools": ["query_costs"], "no_fabrication": True},
    },
    {
        "input": {"message": "Compare this week vs last week"},
        "expected": {"tools": ["compare_costs"], "no_fabrication": True},
    },
    {
        "input": {"message": "Show me anomalies"},
        "expected": {"tools": ["get_anomalies"], "no_fabrication": True},
    },
    {
        "input": {"message": "What filters are available for EC2?"},
        "expected": {"tools": ["search_filters"], "no_fabrication": True},
    },
    {
        "input": {"message": "Any waste recommendations?"},
        "expected": {"tools": ["get_waste_recommendations"], "no_fabrication": True},
    },
]


def _get_langfuse():
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        print("LANGFUSE_SECRET_KEY not set", file=sys.stderr)
        sys.exit(1)
    from langfuse import Langfuse

    return Langfuse()


def seed_dataset() -> None:
    lf = _get_langfuse()
    lf.create_dataset(name=DATASET_NAME)
    for idx, item in enumerate(EVAL_ITEMS):
        lf.create_dataset_item(
            dataset_name=DATASET_NAME,
            input=item["input"],
            expected_output=item["expected"],
            metadata={"index": idx},
        )
    lf.flush()
    print(f"Seeded {len(EVAL_ITEMS)} items into '{DATASET_NAME}'")


def score_tool_correctness(tool_calls: list[dict[str, Any]], expected_tools: list[str]) -> float:
    if not expected_tools:
        return 1.0
    called = {tc["name"] for tc in tool_calls}
    hits = sum(1 for tool_name in expected_tools if tool_name in called)
    return hits / len(expected_tools)


def score_no_fabrication(tool_calls: list[dict[str, Any]], response_text: str) -> bool:
    _ = response_text
    return len(tool_calls) > 0


async def _run_single_item(item_input: dict[str, Any]) -> dict[str, Any]:
    from .server import ChatRequest, MCPBridge, _run_chat_pipeline_inner

    account_id = os.getenv("FINOUT_ACCOUNT_ID", "eval")
    session_mcp = MCPBridge()
    await session_mcp.start(account_id)

    request = ChatRequest(
        message=item_input["message"],
        model=os.getenv("EVAL_MODEL", "claude-sonnet-4-20250514"),
        conversation_history=[],
    )
    try:
        return await _run_chat_pipeline_inner(request, session_mcp, session_id="eval-run")
    finally:
        await session_mcp.stop()


def run_experiment(name: str) -> None:
    lf = _get_langfuse()
    dataset = lf.get_dataset(DATASET_NAME)

    for item in dataset.items:
        print(f"Running: {item.input['message']}")
        result = asyncio.run(_run_single_item(item.input))
        tool_calls = result.get("tool_calls", [])
        response_text = result.get("response", "")
        expected = item.expected_output or {}

        correctness = score_tool_correctness(tool_calls, expected.get("tools", []))
        fabrication_ok = score_no_fabrication(tool_calls, response_text)

        trace = lf.trace(
            name=f"eval:{item.input['message'][:50]}",
            input=item.input,
            output={"response": response_text, "tool_calls": [tc["name"] for tc in tool_calls]},
            metadata={"run_name": name, "response_length": len(response_text)},
        )
        item.link(trace, run_name=name)
        trace.score(name="tool_correctness", value=correctness, data_type="NUMERIC")
        trace.score(
            name="no_fabrication",
            value=1.0 if fabrication_ok else 0.0,
            data_type="NUMERIC",
        )

        print(
            f"  tool_correctness={correctness:.1f}  "
            f"no_fabrication={fabrication_ok}  "
            f"tools={[tc['name'] for tc in tool_calls]}"
        )

    lf.flush()
    print(f"\nExperiment '{name}' complete — check Langfuse Datasets tab")


def main() -> None:
    parser = argparse.ArgumentParser(prog="billy.evaluation")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("seed", help="Seed the eval dataset in Langfuse")

    run_parser = sub.add_parser("run", help="Run an experiment")
    run_parser.add_argument("--name", required=True, help="Experiment run name")

    args = parser.parse_args()
    if args.command == "seed":
        seed_dataset()
    elif args.command == "run":
        run_experiment(args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
