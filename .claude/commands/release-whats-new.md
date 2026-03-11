---
description: Create a Billy release commit — bumps the minor version and prepends a categorized changelog entry (External MCP, Internal MCP, Billy).
---

# Release What's New

Use this skill when packaging a new Billy version with changelog updates.

## Workflow

1. Look at `git diff --stat HEAD` and recent commits to understand what changed.
2. Draft a release title and bullets for each category (use `"No changes"` if nothing changed):
   - External MCP
   - Internal MCP
   - Billy

   **Changelog entries must be customer-facing and functionality-focused.**
   Describe what users can now do or what changed in behavior — not how it was implemented.
   ❌ "Switch dependency detection from static analysis to runtime inference"
   ✅ "Cost breakdowns now detect shared dependencies automatically"
3. Run:

```bash
uv run python scripts/release_minor_with_changelog.py \
  --title "<release title>" \
  --external "<bullet>" \
  --internal "<bullet>" \
  --billy "<bullet>" \
  --commit
```

Repeat `--external`, `--internal`, `--billy` for multiple bullets per category.

4. Verify:
   - `packages/billy/pyproject.toml` minor version incremented (`x.y.z` → `x.(y+1).0`)
   - `packages/billy/src/billy/changelog.py` has the new entry at index 0
