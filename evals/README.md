# Evaluation

`evals/cases.json` is the source of truth for evaluation cases.

## Running

```bash
# Local regression (no dataset seeding needed)
uv run --project packages/billy python -m billy.evaluation run --name local-regression

# Seed Langfuse dataset, then run from it
uv run --project packages/billy python -m billy.evaluation seed
uv run --project packages/billy python -m billy.evaluation run --name dataset-regression --source dataset

# Gated run (exits non-zero on threshold failures)
uv run --project packages/billy python -m billy.evaluation run --name gated-regression --enforce-thresholds

# Verbose with failure details
uv run --project packages/billy python -m billy.evaluation run --name debug-regression --report-limit 15 --verbose
```

## Case format

```json
{
  "id": "unique_id",
  "description": "what this tests",
  "prompt": "User question",
  "suites": ["langfuse"],
  "tags": ["routing", "financial_plans"],
  "expected": {
    "tools": ["get_financial_plans"],
    "args": { "get_financial_plans": { "name": {"$regex": "(?i)aws"} } },
    "terminal_tool": "get_financial_plans",
    "allowed_prefix_tools": ["search_filters"],
    "response_checks": ["mentions budget amount"],
    "expects_text": true,
    "expects_chart": false,
    "no_fabrication": true
  }
}
```

## Expected fields

- `tools` — tools that must be called
- `args` — argument assertions per tool (supports `$regex`, `$present`, exact match)
- `terminal_tool` — the business tool that should ultimately satisfy the prompt
- `allowed_prefix_tools` — acceptable setup tools before the terminal tool
- `response_checks` — concrete answer requirements for the LLM judge
- `expects_text` / `expects_chart` — what the response should include

## Metrics

Gate metrics (enforced with `--enforce-thresholds`):

- `tool_correctness >= 0.90`
- `tool_orchestration >= 0.80`
- `tool_args >= 0.80`
- `no_fabrication >= 1.00`

Quality metrics (informational):

- `response_quality`, `answers_question`, `states_key_result`
- `grounded_in_tool_output`, `directness`, `actionability`, `interaction_quality`

Infrastructure diagnostics:

- `visible_answer_present`, `final_text_present`, `chart_answer_present`

## Notes

- `submit_feedback` is ignored by the orchestration evaluator.
- `render_chart` is treated as an allowed post-terminal presentation helper.
- `search_filters`, `get_filter_values`, `get_usage_unit_types`, `get_account_context` are default allowed prefix tools.
