FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY opcoes ./opcoes

RUN uv sync --frozen --no-dev \
    && /app/.venv/bin/pip install --no-cache-dir gunicorn==23.0.0 \
    && /app/.venv/bin/playwright install --with-deps chromium

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:8000", "opcoes.web:create_app()"]

