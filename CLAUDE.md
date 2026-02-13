# Claude Code Guidelines for Finout MCP

## Documentation Philosophy

**Keep it concise.** Write documentation that people will actually read.

### ❌ Don't
- Write verbose explanations that repeat obvious information
- Add historical context about migrations or changes ("we switched from X to Y")
- Explain every detail - assume the reader is competent
- Create separate docs for every small topic

### ✅ Do
- Write clear, actionable instructions
- Focus on what the user needs to know now
- Use examples instead of long explanations
- Keep READMEs under 200 lines

## Code Philosophy

**Clean code doesn't explain itself.** It just works.

### ❌ Don't
- Add comments explaining that we "migrated from old API"
- Use names like "new_api_client" or "legacy_handler"
- Keep commented-out old code "for reference"
- Add TODO comments about future refactors

### ✅ Do
- Name things clearly based on what they do now
- Delete old code completely
- Write self-explanatory code
- Add comments only for non-obvious business logic

## Naming Conventions

**Name things for what they ARE, not what they WERE or WILL BE.**

❌ Bad:
- `new_cost_api`
- `internal_api_v2`
- `legacy_client`
- `deprecated_get_costs`

✅ Good:
- `cost_api`
- `client`
- `get_costs`

## Making Changes

When refactoring or improving code:

1. **Just do it** - Don't leave breadcrumbs about the change
2. **Delete old code** - No commented-out "for reference" blocks
3. **Update docs** - Remove outdated info, don't add migration notes
4. **Clean names** - Rename things to reflect current reality

## Examples

### Bad Documentation
```markdown
# Cost Query API

## Migration Notice
We recently migrated from the public API to the internal API. The old approach
used viewId-based queries, but the new approach uses flexible filters...

[300 lines of historical context and detailed explanations]
```

### Good Documentation
```markdown
# Cost Queries

Query costs with filters:

```python
filters = [{"key": "service", "value": "ec2", "operator": "is"}]
costs = await client.query_costs("last_30_days", filters)
```

See examples/ for more.
```

### Bad Code
```python
# NEW: Internal API client (migrated from public API on 2026-02-13)
class FinoutClient:
    def __init__(self):
        # Using internal API now, not public API
        self.internal_api_url = ...  # This replaces the old base_url
```

### Good Code
```python
class FinoutClient:
    def __init__(self):
        self.api_url = os.getenv("FINOUT_API_URL")
```

## Testing

- Write tests for current behavior
- Don't test "migration compatibility"
- Delete tests for removed features

## Git Commits

Good commit messages:
- "Fix dropdown positioning"
- "Add cost breakdown tool"
- "Remove unused imports"

Bad commit messages:
- "Migrate from old API to new internal API"
- "Refactor legacy code to use new patterns"
- "Remove deprecated public API references"

Just describe what changed, not the journey.

---

## Automated Quality Checks

**IMPORTANT:** After making code changes, always run quality checks.

### When to Run

Run checks after:
- Editing any `.py` file
- Adding new functions or classes
- Refactoring code
- **Before marking any task as completed**

### Commands

```bash
cd packages/mcp-server

# Run all checks (REQUIRED before completing tasks)
make check

# Auto-fix linting issues
make format

# Optional: Type checking (informational only)
make typecheck
```

**`make check` runs:**
1. ✅ **Linting** (`ruff`) - Code style, imports, common errors
2. ✅ **Type checking** (`mypy`) - Type annotations must be correct
3. ✅ **Tests** (`pytest`) - All 28 tests must pass

### Workflow

```bash
# 1. Make code changes
# 2. Fix linting
make format

# 3. Run checks
make check

# 4. If tests fail, fix code and repeat
# 5. If all pass, mark task complete
```

### Pre-commit Hooks

Installed and active:
- **On commit**: Runs `ruff` (lint + format)
- **On push**: Runs `pytest` (all tests)

If pre-commit fails, fix issues and commit again.

### Rules

- ✅ All linting must pass
- ✅ All type checking must pass
- ✅ All tests must pass (28/28)
- ❌ Don't mark tasks complete if `make check` fails
- ❌ Don't skip checks "to save time"
- ❌ Don't disable type checkers - fix the code instead

---

**Remember:** Users care about what the code does now, not its history.
