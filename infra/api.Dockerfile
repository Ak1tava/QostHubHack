FROM python:3.12.14-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /workspace/services/api
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --locked --no-dev
COPY services/api/app ./app
COPY services/api/migrations ./migrations
COPY services/api/alembic.ini ./alembic.ini
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /workspace/data/photos /workspace/data/live-budget \
    && chown -R app:app /workspace/data/photos /workspace/data/live-budget
USER app
EXPOSE 8000
CMD ["/workspace/services/api/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
