FROM python:3.11-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 3 https://rolesanywhere.amazonaws.com/releases/1.8.5/X86_64/Linux/Amzn2023/aws_signing_helper -o /usr/local/bin/aws_signing_helper \
    && echo 'beec9ed1c492d93db809890f16713e3556353294b823c2184ad4e891f1b2b54d  /usr/local/bin/aws_signing_helper' | sha256sum -c - \
    && chmod 755 /usr/local/bin/aws_signing_helper
WORKDIR /app
COPY Autoclick-MCP/pyproject.toml Autoclick-MCP/pyproject.toml
COPY Autoclick-MCP/autoclick_mcp Autoclick-MCP/autoclick_mcp
COPY Autoclick-IA/pyproject.toml Autoclick-IA/uv.lock Autoclick-IA/
COPY Autoclick-IA/app Autoclick-IA/app
COPY Autoclick-IA/deploy/entrypoint.py Autoclick-IA/deploy/entrypoint.py
RUN uv sync --project Autoclick-IA --frozen --no-dev --no-editable --python /usr/local/bin/python \
    && useradd --create-home --uid 10001 autoclick \
    && mkdir -p /var/lib/autoclick /run/autoclick \
    && chown autoclick:autoclick /var/lib/autoclick /run/autoclick
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AUTOCLICK_AI_HOST=0.0.0.0 AUTOCLICK_AI_PORT=8001 \
    AUTOCLICK_CLOUD_OUTBOX=/var/lib/autoclick/usage-outbox.sqlite3
USER autoclick
WORKDIR /app/Autoclick-IA
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=15s --start-period=90s --retries=3 CMD ["/app/Autoclick-IA/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=12).read()"]
CMD ["/app/Autoclick-IA/.venv/bin/python", "deploy/entrypoint.py"]
