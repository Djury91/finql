# syntax=docker/dockerfile:1
# A FinQL-alkalmazás képe: két lépcső. Az első uv-vel telepíti a függőségeket a lock fájl
# szerint, a második csak a kész környezetet és a futáshoz kellő fájlokat kapja (fordító, uv,
# cache nélkül), és nem rootként fut. Parancsok: serve (alapértelmezett) és setup, lásd
# docker/entrypoint.sh.

ARG PYTHON_IMAGE=python:3.12-slim-trixie

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Előbb csak a függőségek: ez a réteg addig cache-ből jön, amíg a lock fájl nem változik.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# A projekt szerkeszthető módban kerül a környezetbe: a kód a /app/src-ben marad, és onnan
# találja meg a db/ SQL-fájljait (core/sql_files.py).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM ${PYTHON_IMAGE}
RUN groupadd --system --gid 10001 finql \
    && useradd --system --uid 10001 --gid finql --home-dir /app --no-create-home finql
WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FINQL_ENV=prod
# A fájlok a root tulajdonában maradnak: a futó folyamat nem írhatja át a saját kódját.
COPY --from=build /app /app
COPY alembic.ini ./
COPY migrations ./migrations
COPY db ./db
COPY data ./data
COPY manual-demo/magyar ./manual-demo/magyar
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/finql-entrypoint
USER finql
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=2)"]
ENTRYPOINT ["finql-entrypoint"]
CMD ["serve"]
