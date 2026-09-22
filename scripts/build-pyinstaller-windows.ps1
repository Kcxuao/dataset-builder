$ErrorActionPreference = 'Stop'

$ProjectDir = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $ProjectDir 'dist\pyinstaller'
$WorkDir = Join-Path $ProjectDir 'build\pyinstaller'

Set-Location $ProjectDir
pnpm --dir frontend build
uv run pyinstaller --noconfirm --clean --onedir --name dataset-builder `
  --paths src `
  --distpath $OutputDir `
  --workpath $WorkDir `
  --specpath $WorkDir `
  --add-data "$ProjectDir\src\dataset_builder\web;dataset_builder/web" `
  --add-data "$ProjectDir\migrations;migrations" `
  --add-data "$ProjectDir\alembic.ini;." `
  --collect-all alembic `
  --collect-all aiosqlite `
  --collect-all asyncpg `
  src/dataset_builder/desktop.py
