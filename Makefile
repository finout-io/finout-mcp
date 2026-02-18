.PHONY: dev-vectiqor

# Start FastAPI backend + Vite frontend dev server via uv script runner
dev-vectiqor:
	@cd packages/vectiqor && uv run vectiqor-dev
