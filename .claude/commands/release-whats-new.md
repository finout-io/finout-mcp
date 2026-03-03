# release-whats-new

Create a Billy release by bumping the Billy minor version and prepending a categorized changelog entry.

Required categories:
- External MCP
- Internal MCP
- Billy

Run:

```bash
uv run python scripts/release_minor_with_changelog.py \
  --title "$TITLE" \
  --external "$EXTERNAL_1" \
  --internal "$INTERNAL_1" \
  --billy "$BILLY_1" \
  --commit
```

Repeat `--external`, `--internal`, `--billy` as needed.

Verify after running:
- `packages/billy/pyproject.toml` has a minor bump (`x.y.z` -> `x.(y+1).0`)
- `packages/billy/src/billy/changelog.py` has the new entry first
