# Image for the AutoPatch agent itself (the sandbox image is Dockerfile.sandbox).
FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY docker ./docker
COPY eval ./eval
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["autopatch"]
