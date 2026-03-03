.PHONY: dev-billy build-mcp-wheel

# Start FastAPI backend + Vite frontend dev server via uv script runner
dev-billy:
	@cd packages/billy && uv run billy-dev

# Build finout-mcp-server wheel+sdist into packages/mcp-server/dist
build-mcp-wheel:
	@$(MAKE) -C packages/mcp-server build
