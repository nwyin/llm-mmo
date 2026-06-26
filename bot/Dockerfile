# Image for running the bot on an always-on host.
# Build from the REPO ROOT so the bot can read knowledge/, personas/, .agents/skills/, and
# (for the background knowledge pull) the .git directory:
#   docker build -f bot/Dockerfile -t llm-mmo .
#   docker run --restart=always --env-file bot/.env -v llm_mmo_data:/data llm-mmo
FROM python:3.12-slim

# git is required at RUNTIME for the knowledge pull loop (pull_interval_seconds > 0).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . /app
RUN chmod +x /app/bot/docker-entrypoint.sh

# Install locked runtime deps (no dev group) into bot/.venv.
WORKDIR /app/bot
RUN uv sync --frozen --no-dev

# All mutable state lives on the mounted volume, kept out of the immutable checkout.
ENV STATE_DIR=/data
VOLUME ["/data"]

# Run from the repo root so REPO_ROOT (knowledge/, personas/, .git) resolves to /app.
WORKDIR /app
ENTRYPOINT ["/app/bot/docker-entrypoint.sh"]
