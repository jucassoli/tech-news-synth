# syntax=docker/dockerfile:1.7

# --- builder stage: uv resolves deps into /app/.venv from the lockfile ---
FROM python:3.12-slim-bookworm AS builder

# Pin uv via official image (tag locked per A6).
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Layer 1: deps-only (maximizes cache hits on source edits).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Layer 2: project install.
COPY src/ ./src/
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime stage: slim, no build tools, non-root ---
FROM python:3.12-slim-bookworm AS runtime

# Non-root user (T-02-05).
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Copy venv + source from builder.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

# Data directory for logs + paused marker (volume mount target).
RUN mkdir -p /data/logs /app/config \
 && chown -R app:app /data /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

USER app

# INFRA-01 healthcheck: lightweight import smoke (Phase 2 extends to DB ping).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import tech_news_synth" || exit 1

# Exec form CMD — CRITICAL for SIGTERM propagation (PITFALLS #2 / T-02-07).
CMD ["python", "-m", "tech_news_synth"]
