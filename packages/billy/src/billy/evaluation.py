"""Langfuse evaluation dataset seeder and experiment runner for Billy."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

from langfuse.experiment import Evaluation

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
        return await _run_chat_pipeline_inner(request, session_mcp, session_id="eval-run")
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
    response_text = output.get("response", "") if isinstance(output, dict) else str(output)
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

def run_experiment(name: str) -> None:
    lf = _get_langfuse()
    dataset = lf.get_dataset(DATASET_NAME)

    result = lf.run_experiment(
        name=DATASET_NAME,
        run_name=name,
        data=dataset.items,
        task=task,
        evaluators=[eval_tool_correctness, eval_no_fabrication, eval_response_quality],
    )

    print(f"\nExperiment '{name}' complete — {len(result.item_results)} items")
    print("Check the Langfuse Datasets tab for scores.")


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
