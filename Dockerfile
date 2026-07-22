FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY insightforge ./insightforge
RUN pip install .

COPY benchmark ./benchmark
COPY .env.example ./

RUN useradd --create-home --uid 10001 insightforge \
    && mkdir -p /app/.runtime/data /app/.runtime/artifacts /app/.runtime/datasets /app/.runtime/benchmark /app/.runtime/tmp \
    && chown -R insightforge:insightforge /app

USER insightforge

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
