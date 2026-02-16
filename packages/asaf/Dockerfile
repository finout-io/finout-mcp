# Multi-stage build for ASAF (Ask the Smart AI of Finout)
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
COPY packages/asaf /app/packages/asaf
COPY packages/mcp-server /app/packages/mcp-server

# Install dependencies for both packages
WORKDIR /app/packages/asaf
RUN pip install --no-cache-dir -e .

WORKDIR /app/packages/mcp-server
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

# Set working directory to ASAF
WORKDIR /app/packages/asaf

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

# Run ASAF server
CMD ["uvicorn", "asaf.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
