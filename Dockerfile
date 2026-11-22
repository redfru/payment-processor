FROM python:3.12-slim AS base
WORKDIR /service
ENV PYTHONUNBUFFERED=1 PATH="/service/.venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.11.27
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM base AS runtime
COPY alembic.ini .
COPY migrations migrations
COPY app app
USER 65534:65534
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS webhook
COPY tests/receiver.py /demo/receiver.py

FROM runtime AS tests
USER root
RUN uv sync --locked --no-install-project
COPY tests tests
USER 65534:65534
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM runtime AS production
