#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$project_dir/dist/pyinstaller"
work_dir="$project_dir/build/pyinstaller"

cd "$project_dir"
pnpm --dir frontend build
uv run pyinstaller --noconfirm --clean --onedir --name dataset-builder \
  --paths src \
  --distpath "$output_dir" \
  --workpath "$work_dir" \
  --specpath "$work_dir" \
  --add-data "$project_dir/src/dataset_builder/web:dataset_builder/web" \
  --add-data "$project_dir/migrations:migrations" \
  --add-data "$project_dir/alembic.ini:." \
  --collect-all alembic \
  --collect-all aiosqlite \
  --collect-all asyncpg \
  src/dataset_builder/desktop.py
