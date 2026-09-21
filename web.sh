#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"

WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-8000}"
WEB_LOG_LEVEL="${WEB_LOG_LEVEL:-warning}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 错误：$*" >&2
}

if ! command -v uv >/dev/null 2>&1; then
    error "未找到 uv，请先安装 uv 并确保它位于 PATH 中。"
    exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
    error "未找到 pnpm，请先安装 pnpm 并确保它位于 PATH 中。"
    exit 1
fi

if [[ ! -f "$PROJECT_DIR/pyproject.toml" ]]; then
    error "未找到 pyproject.toml。"
    exit 1
fi

if [[ ! -f "$PROJECT_DIR/alembic.ini" ]]; then
    error "未找到 alembic.ini。"
    exit 1
fi

if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
    error "未找到 frontend/package.json。"
    exit 1
fi

log "正在构建前端..."
cd "$FRONTEND_DIR"
pnpm build
log "前端构建完成。"

log "正在执行数据库迁移..."
cd "$PROJECT_DIR"
uv run alembic upgrade head
log "数据库迁移完成。"

log "Dataset Builder 正在启动：http://${WEB_HOST}:${WEB_PORT}/"

exec uv run uvicorn dataset_builder.api:app \
    --host "$WEB_HOST" \
    --port "$WEB_PORT" \
    --no-access-log \
    --log-level "$WEB_LOG_LEVEL" \
    "$@"