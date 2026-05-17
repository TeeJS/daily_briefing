FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY briefing/ ./briefing/

RUN pip install --no-cache-dir .

# Volume mounts provided by Unraid:
#   /app/secrets    — OAuth tokens, API keys (RW; refresh tokens rotate)
#   /app/briefings  — rendered HTML archive (RW)
#   /app/logs       — log output (RW)

ENTRYPOINT ["python", "-m", "briefing.run"]
