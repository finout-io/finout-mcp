# Stage 1: Build frontend on native builder platform to avoid
# esbuild/runtime crashes under cross-arch emulation.
ARG BUILDPLATFORM
FROM --platform=$BUILDPLATFORM node:20-bookworm-slim AS frontend
RUN corepack enable
WORKDIR /app/frontend
COPY packages/vectiqor/frontend/package.json packages/vectiqor/frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY packages/vectiqor/frontend/ .
RUN pnpm build

# Stage 2: Build Python packages
FROM python:3.11-slim AS builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy workspace files
COPY packages/vectiqor /app/packages/vectiqor
COPY packages/mcp-server /app/packages/mcp-server
COPY packages/vectiqor-mcp-internal /app/packages/vectiqor-mcp-internal

# Install dependencies for both packages
WORKDIR /app/packages/vectiqor
RUN pip install --no-cache-dir -e .

WORKDIR /app/packages/mcp-server
RUN pip install --no-cache-dir -e .

WORKDIR /app/packages/vectiqor-mcp-internal
RUN pip install --no-cache-dir -e .

# Final stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
WORKDIR /app
COPY --from=builder /app /app

# Copy built frontend into the static directory FastAPI serves
COPY --from=frontend /app/frontend/dist /app/packages/vectiqor/src/vectiqor/static/

# Set working directory to VECTIQOR
WORKDIR /app/packages/vectiqor

# Expose port
EXPOSE 8000

# Environment variables (override at runtime)
ENV ANTHROPIC_API_KEY=""
ENV FINOUT_CLIENT_ID=""
ENV FINOUT_SECRET_KEY=""
ENV FINOUT_INTERNAL_API_URL=""
# DATABASE_URL will be set by docker-compose or runtime environment

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run VECTIQOR server
CMD ["uvicorn", "vectiqor.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
