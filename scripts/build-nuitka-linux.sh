#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$project_dir/dist/nuitka"

if ! command -v patchelf >/dev/null 2>&1; then
  echo "需要 patchelf：请先安装后重试（Debian/Ubuntu：sudo apt install patchelf）" >&2
  exit 1
fi

cd "$project_dir"
pnpm --dir frontend build
uv run nuitka --standalone --assume-yes-for-downloads \
  --output-dir="$output_dir" \
  --output-filename=dataset-builder \
  --include-package=dataset_builder \
  --include-package=aiosqlite \
  --include-package=asyncpg \
  --include-data-dir=src/dataset_builder/web=dataset_builder/web \
  --include-data-dir=migrations=migrations \
  --include-data-file=alembic.ini=alembic.ini \
  src/dataset_builder/desktop.py
