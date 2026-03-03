---
name: release-whats-new
description: Create a Billy release commit by bumping Billy minor version and prepending a categorized what's-new entry (External MCP, Internal MCP, Billy).
---

# Release What's New

Use this skill when the user wants to package a new Billy version with changelog updates.

## Workflow

1. Confirm the release title and bullets for all relevant categories:
   - External MCP
   - Internal MCP
   - Billy
2. Run:

```bash
uv run python scripts/release_minor_with_changelog.py \
  --title "<release title>" \
  --external "<bullet>" \
  --internal "<bullet>" \
  --billy "<bullet>" \
  --commit
```

3. Verify:
   - `packages/billy/pyproject.toml` minor version incremented (`x.y.z` -> `x.(y+1).0`)
   - `packages/billy/src/billy/changelog.py` has new entry at index 0
4. If tests/build are requested, run them after the release commit.

## Notes

- Repeat `--external`, `--internal`, and `--billy` for multiple bullets.
- Use `--date YYYY-MM-DD` only for backfilled releases.
- Use `--commit-message` to override the default commit title.
