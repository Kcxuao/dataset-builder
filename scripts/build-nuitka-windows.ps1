$ErrorActionPreference = 'Stop'

$ProjectDir = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $ProjectDir 'dist\nuitka'

Set-Location $ProjectDir
pnpm --dir frontend build
uv run nuitka --standalone --assume-yes-for-downloads `
  --output-dir=$OutputDir `
  --output-filename=dataset-builder.exe `
  --include-package=dataset_builder `
  --include-package=aiosqlite `
  --include-package=asyncpg `
  --include-data-dir=src/dataset_builder/web=dataset_builder/web `
  --include-data-dir=migrations=migrations `
  --include-data-file=alembic.ini=alembic.ini `
  src/dataset_builder/desktop.py
