FROM python:3.12-slim

RUN adduser --system --group --shell /bin/bash --home /app app
RUN pip install pdm

WORKDIR /app
COPY pyproject.toml pdm.lock ./

USER app:app

RUN pdm install -G dev
COPY dispatcher dispatcher
COPY tests tests
COPY manifests manifests

ENV PYTHONPATH="."

CMD ["pdm", "run", "python", "pytest", "test/integration"]
