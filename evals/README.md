# Evaluation Strategy

`evals/cases.json` is the shared source of truth for evaluation cases.

Use Promptfoo for fast tool-contract regressions:

- Goal: verify tool routing and key argument extraction before merging.
- Scope: prompts that can be judged from the first tool call without standing up the full Billy stack.
- Command:

```bash
cd evals
PROMPTFOO_CONFIG_DIR=/tmp/promptfoo \
PROMPTFOO_DISABLE_WAL_MODE=true \
ANTHROPIC_API_KEY=... \
npx promptfoo eval -c promptfoo.yaml
```

Use Langfuse for full-pipeline experiments:

- Goal: run the real Billy chat loop, capture traces, and score tool behavior plus user-visible answer quality.
- Default mode uses the local shared cases directly, so you can iterate without re-seeding a dataset.
- Commands:

```bash
uv run --project packages/billy python -m billy.evaluation run --name local-regression
uv run --project packages/billy python -m billy.evaluation seed
uv run --project packages/billy python -m billy.evaluation run --name dataset-regression --source dataset
uv run --project packages/billy python -m billy.evaluation run --name gated-regression --source local --enforce-thresholds
uv run --project packages/billy python -m billy.evaluation run --name debug-regression --source local --report-limit 15
```

Recommended split:

- Promptfoo: pre-merge gate for `tool_routing` and `tool_args`.
- Langfuse: experiment history, judge scores, latency/cost tradeoffs, and production-like regression tracking.

Langfuse notes:

- Langfuse evaluates the full ordered tool trace, not just the first tool call.
- Use `expected.required_tools` for tools that must appear anywhere in the run.
- Use `expected.terminal_tool` for the business tool that should ultimately satisfy the prompt.
- Use `expected.allowed_prefix_tools` for acceptable setup tools before the terminal tool, such as `search_filters`.
- Use `expected.response_checks` to give the judge concrete answer requirements.
- Use `expected.expects_text` when a prompt should produce accompanying narrative text.
- Use `expected.expects_chart` when a prompt should produce a rendered chart.
- `submit_feedback` is ignored entirely by the orchestration evaluator.
- `render_chart` is treated as an allowed post-terminal presentation helper.
- `response_quality` is LLM-judged with a structured rubric and returns a short reason in the eval comment.
- Additional LLM-judged metrics are reported locally to help triage weak answers:
  - `answers_question`
  - `states_key_result`
  - `grounded_in_tool_output`
  - `directness`
  - `actionability`
  - `interaction_quality`
- `interaction_quality` judges the full interaction, including whether the tool choices and overall flow made sense for the user's request.
- Default thresholds are:
  - `tool_correctness >= 0.90`
  - `tool_orchestration >= 0.80`
  - `tool_args >= 0.80`
  - `no_fabrication >= 1.00`
- `visible_answer_present`, `response_quality`, `final_text_present`, and `chart_answer_present` are reported locally as diagnostics, but are not global gate metrics by default.
- The local report also prints a `Top Communication Failures` section based on:
  - `answers_question`
  - `states_key_result`
  - `directness`
  - `response_quality`
  - `visible_answer_present`
- Once the judge is tuned and stable, `response_quality` can be restored as a hard threshold.
- Pass `--enforce-thresholds` to exit non-zero when any threshold is missed.
- Use `--report-limit` to control how many failing cases and failing tags are printed locally after each run.

Promptfoo notes:

- `promptfoo.yaml` is the only canonical Promptfoo config in this repo.
- Routing assertions are implemented as local Javascript checks that verify required tools are present.
- Argument assertions are implemented as local Javascript checks over the extracted tool payloads.
- Promptfoo also needs a writable config dir in this environment, so set `PROMPTFOO_CONFIG_DIR` explicitly.
