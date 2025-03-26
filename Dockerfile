FROM python:3.12-slim

# ENV K8S_IN_CLUSTER=

RUN adduser --system --group --shell /bin/bash --home /app app
RUN pip install pdm

WORKDIR /app
COPY pyproject.toml pdm.lock ./

USER app:app

RUN pdm install --prod
COPY dispatcher dispatcher

CMD ["pdm", "run", "prod"]
