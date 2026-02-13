.PHONY: test lint typecheck format check install hooks clean

# Run all checks
check: lint typecheck test

# Run tests
test:
	uv run pytest tests/ -v

# Run linting
lint:
	uv run ruff check src/ tests/

# Fix linting issues
format:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

# Run type checking
typecheck:
	uv run mypy src/

# Install dependencies
install:
	uv sync

# Install pre-commit hooks
hooks:
	uv run pre-commit install
	uv run pre-commit install --hook-type pre-push

# Clean build artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
