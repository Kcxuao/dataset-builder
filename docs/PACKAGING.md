# 桌面发布打包

桌面发布包运行本地 FastAPI 服务，并在默认浏览器中打开工作台。它不依赖 `uv`、`pnpm`、Node.js 或预先安装的 Python。

发布版默认使用 SQLite；数据文件和导出文件写入用户目录，而不是可执行文件目录：Windows 为 `%LOCALAPPDATA%\\dataset-builder`，Linux 为 `$XDG_DATA_HOME/dataset-builder`（未设置时为 `~/.local/share/dataset-builder`）。可设置 `DATASET_BUILDER_HOME` 指定其他目录。

首次启动会自动执行数据库迁移。可用 `DATASET_BUILDER_HOST`、`DATASET_BUILDER_PORT` 调整监听地址和端口；设置 `DATASET_BUILDER_OPEN_BROWSER=false` 可禁止自动打开浏览器。显式设置 `DATABASE_PROVIDER`、`DATABASE_URL`、`SQLITE_PATH` 或 `EXPORT_DIR` 时，启动入口不会覆盖它们。

## 前置条件

- 使用 `uv sync --group dev` 安装 PyInstaller 与 Nuitka。
- 使用 `pnpm install --frozen-lockfile` 安装前端依赖。
- Nuitka 需要原生 C 编译器：Linux 使用 GCC 和 `patchelf`，Windows 使用 Visual Studio Build Tools（含 MSVC）。Debian/Ubuntu 可执行 `sudo apt install build-essential patchelf`。
- 必须在目标系统原生构建，不能从 Linux 生成 Windows `.exe`，也不能从 Windows 生成 Linux 可执行文件。

## PyInstaller

Linux：

```bash
bash scripts/build-pyinstaller-linux.sh
```

Windows PowerShell：

```powershell
pwsh -File scripts/build-pyinstaller-windows.ps1
```

输出位于 `dist/pyinstaller/dataset-builder/`。这是优先推荐的兼容性发布包。

## Nuitka

Linux：

```bash
bash scripts/build-nuitka-linux.sh
```

Windows PowerShell：

```powershell
pwsh -File scripts/build-nuitka-windows.ps1
```

输出位于 `dist/nuitka/` 下的 Nuitka `.dist` 目录。Nuitka 编译耗时更长，但启动性能与源码保护更好；仍应将整个 `.dist` 目录压缩发布，不要只分发其中的可执行文件。

每次构建都会先执行 `pnpm build`，把前端静态资源、Alembic 配置和所有迁移一并打包。发布前至少应在未安装 Python 与 Node.js 的干净虚拟机上验证：首次启动迁移、导入、生成前预览、审核和导出。
