FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY migrations/ ./migrations/
RUN uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --locked --no-dev \
    && useradd --system --create-home --home-dir /home/lifeos lifeos \
    && mkdir -p /data \
    && chown -R lifeos:lifeos /app /data

ENV PATH="/app/.venv/bin:$PATH"
USER lifeos
EXPOSE 8000
CMD ["uvicorn", "personal_ai_life_os.main:app", "--host", "0.0.0.0", "--port", "8000"]
