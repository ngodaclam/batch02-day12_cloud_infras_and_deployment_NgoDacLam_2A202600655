# ============================================================
# Production Dockerfile — Multi-stage build, optimized size
# ============================================================

# ── Stage 1: Builder ────────────────────────────────────────
# Install dependencies in a temporary stage to keep the
# final image clean and small.
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies for compiled packages
RUN apt-get update && apt-get install -y gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Stage 2: Runtime ────────────────────────────────────────
# Use a clean slim image — no build tools, no cache, minimal size.
FROM python:3.11-slim AS runtime

# Create non-root user for security
RUN groupadd -r agent && useradd -r -g agent -d /app agent

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /root/.local /home/agent/.local

# Copy application source code
COPY app/ ./app/

# Set ownership to non-root user
RUN chown -R agent:agent /app

USER agent

# Configure Python environment
ENV PATH=/home/agent/.local/bin:$PATH
ENV PYTHONPATH=/app/app:/app:/home/agent/.local/lib/python3.11/site-packages
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Container health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

# Run with uvicorn — 2 workers for production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
