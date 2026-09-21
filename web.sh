#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-8000}"
WEB_LOG_LEVEL="${WEB_LOG_LEVEL:-warning}"

if ! command -v uv >/dev/null 2>&1; then
    echo "错误：未找到 uv，请先安装 uv 并确保它位于 PATH 中。" >&2
    exit 1
fi

cd "$PROJECT_DIR"

echo "Dataset Builder 正在启动：http://${WEB_HOST}:${WEB_PORT}/"

exec uv run uvicorn dataset_builder.api:app \
    --host "$WEB_HOST" \
    --port "$WEB_PORT" \
    --no-access-log \
    --log-level "$WEB_LOG_LEVEL" \
    "$@"