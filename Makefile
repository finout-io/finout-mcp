.PHONY: dev-vectiqor build-mcp-wheel

# Start FastAPI backend + Vite frontend dev server via uv script runner
dev-vectiqor:
	@cd packages/vectiqor && uv run vectiqor-dev

# Build finout-mcp-server wheel+sdist into packages/mcp-server/dist
build-mcp-wheel:
	@$(MAKE) -C packages/mcp-server build
