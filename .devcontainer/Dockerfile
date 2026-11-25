FROM ghcr.io/astral-sh/uv:0.12.5 AS uv
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

COPY --from=uv /uv /uvx /usr/local/bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
