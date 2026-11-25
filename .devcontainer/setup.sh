#!/usr/bin/env bash
set -euo pipefail

uv sync --locked --python 3.11 --all-groups
cd web
npm ci
npx playwright install --with-deps chromium
