# Minimal image for running the bot on an always-on host.
# Build from the repo root so the bot can read ../knowledge and ../personas:
#   docker build -f bot/Dockerfile -t llm-mmo .
#   docker run --env-file bot/.env llm-mmo
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY . /app

WORKDIR /app/bot
RUN uv sync --no-dev

# Run as a module from the repo root so relative paths to knowledge/ and personas/ resolve.
WORKDIR /app
CMD ["uv", "--project", "bot", "run", "python", "-m", "bot"]
