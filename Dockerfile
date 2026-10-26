# ==============================================================================
# SafeRoute LLM Gateway - Production Container Image
# ==============================================================================

FROM python:3.11-slim AS base

# System configuration & environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install minimal system utilities (curl for container healthchecks)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user and group
RUN groupadd -g 10001 saferoute && \
    useradd -u 10001 -g saferoute -m -d /home/saferoute -s /bin/bash saferoute

# Set working directory
WORKDIR /app

# Create persistent data directory for SQLite storage and set permissions
RUN mkdir -p /app/data && \
    chown -R saferoute:saferoute /app

# Copy dependency definition and README (for setuptools build)
COPY --chown=saferoute:saferoute pyproject.toml README.md ./

# Install application dependencies
RUN pip install --no-cache-dir .

# Copy application source code
COPY --chown=saferoute:saferoute app ./app
COPY --chown=saferoute:saferoute scripts ./scripts

# Ensure non-root ownership across application files
RUN chown -R saferoute:saferoute /app

# Switch to unprivileged non-root user
USER saferoute

# Expose HTTP port
EXPOSE 8000

# Container liveness health check probe
HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start Uvicorn ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
