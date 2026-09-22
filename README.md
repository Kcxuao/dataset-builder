# Dataset Builder

Dataset Builder 是一个轻量、模块化的 LLM 训练数据集构建工具。它可以把 TXT、Markdown、JSON、JSONL、CSV 等原始数据解析、切分并通过 OpenAI Compatible API 生成训练样本，再经过清洗、校验和人工审核，导出为 Alpaca 或 ShareGPT 数据集。

项目提供 Web 工作台和 CLI，两种入口复用同一套核心能力。内部使用统一的消息格式保存样本，并保留 `SourceDocument → Chunk → TrainingSample` 数据血缘，Alpaca 和 ShareGPT 仅在导出时转换。

## 主要功能

- 导入 TXT、Markdown、JSON、JSONL、CSV 原始文件
- 导入已有 Alpaca、ShareGPT JSON/JSONL 数据集
- 支持固定长度、段落和 Markdown 标题切分
- 使用兼容 OpenAI API 的模型生成 QA、Instruction 和多轮对话样本
- 生成前预览 Chunk，并选择少量 Chunk 试生成
- 空内容过滤、文本规范化、长度检查和精确去重
- 消息结构、角色顺序和目标格式兼容性校验
- 样本筛选、编辑、审核、删除、恢复和定向重新生成
- 数据质量概览与来源追踪
- 多策略数据集扩增和教师答案蒸馏
- 蒸馏候选对比审核
- 创建不可变数据集版本并比较版本差异
- 导出 Alpaca/ShareGPT 的 JSON、JSONL 文件
- 从数据集版本生成 LLaMA-Factory 训练包
- 从蒸馏审核或手工输入构建 DPO 偏好对，并导出 Preference 数据与 DPO 训练包
- 支持 PostgreSQL 标准部署和 SQLite 本地单机运行

## 运行环境

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 和 pnpm（构建 Web 前端时需要）
- PostgreSQL（可选；本地使用 SQLite 时不需要）

## 快速开始

### 1. 安装依赖

```bash
uv sync --group dev
cd frontend
pnpm install --frozen-lockfile
cd ..
```

### 2. 配置数据库

本地体验推荐 SQLite。在项目根目录创建 `.env`：

```dotenv
DATABASE_PROVIDER=sqlite
SQLITE_PATH=dataset-builder.sqlite3
EXPORT_DIR=exports
```

如需使用 PostgreSQL：

```dotenv
DATABASE_PROVIDER=postgresql
DATABASE_URL=postgresql+asyncpg://dataset_builder:password@127.0.0.1:5432/dataset_builder
EXPORT_DIR=exports
```

数据库配置在进程启动时读取。切换数据库后需要重启服务并对目标数据库单独执行迁移；项目不会在 SQLite 和 PostgreSQL 之间自动迁移。

### 3. 启动 Web 工作台

```bash
./web.sh
```

脚本会构建前端、执行 Alembic 迁移并启动服务。默认访问：

- 工作台：<http://127.0.0.1:8000/>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>

可通过环境变量修改监听地址、端口和日志等级：

```bash
WEB_HOST=0.0.0.0 WEB_PORT=8080 WEB_LOG_LEVEL=info ./web.sh
```

启动后，先在“模型配置”中添加 OpenAI、Qwen、DeepSeek、vLLM、Ollama 或其他兼容 OpenAI API 的模型服务，再创建数据集。API Key 不会通过模型列表接口返回。

## Web 使用流程

1. 在“模型配置”中添加并测试模型服务。
2. 在“新建数据集”中上传源文件；已有训练样本导入支持一次选择多个 JSON/JSONL 文件。
3. 选择解析字段、切分方式、生成策略和提示词。
4. 使用构建前预览检查 Chunk；可选择最多 3 个 Chunk 试生成。
5. 启动完整构建并查看后台进度及失败原因。
6. 在项目页检查质量概览，编辑并审核样本。
7. 创建不可变数据集版本，或直接导出审核通过的数据。
8. 按需要导出 Alpaca/ShareGPT JSON/JSONL，或生成 LLaMA-Factory 训练包。

默认导出范围仅包含：校验通过、人工审核通过、未删除且未被替代的样本。多轮对话可无损导出为 ShareGPT；无法无损表达为 Alpaca 的样本会返回明确错误，不会被静默截断。

## CLI 使用

CLI 构建和重试使用环境变量中的默认 OpenAI Compatible 模型配置。在 `.env` 中补充：

```dotenv
LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=your-api-key
LLM_MODEL=your-model
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=1024
LLM_TIMEOUT=60
LLM_CONCURRENCY_LIMIT=4
LLM_MAX_RETRIES=2
LLM_JSON_MODE=false
```

构建数据集：

```bash
uv run dataset-builder build input.md \
  --project-name example \
  --generator qa \
  --splitter auto \
  --max-chars 1000
```

结构化文件可指定字段或列：

```bash
uv run dataset-builder build articles.jsonl --content-field article.body
uv run dataset-builder build records.csv --content-column title --content-column content
```

常用审核和导出命令：

```bash
uv run dataset-builder list PROJECT_ID
uv run dataset-builder show SAMPLE_ID
uv run dataset-builder review SAMPLE_ID approved
uv run dataset-builder retry PROJECT_ID
uv run dataset-builder export PROJECT_ID --format sharegpt --output exports/dataset.jsonl
```

查看全部参数：

```bash
uv run dataset-builder --help
uv run dataset-builder build --help
```

## 手动启动与前端开发

已有前端产物时，可手动迁移并启动后端：

```bash
uv run alembic upgrade head
uv run uvicorn dataset_builder.api:app --host 127.0.0.1 --port 8000
```

开发前端：

```bash
cd frontend
pnpm dev
```

生成生产前端资源：

```bash
cd frontend
pnpm build
```

## 测试与代码检查

```bash
uv run ruff check .
uv run pytest
pnpm --dir frontend build
```

PostgreSQL 集成测试需要提供独立测试数据库：

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@127.0.0.1:5432/dataset_builder_test uv run pytest
```

不要让测试数据库指向保存真实数据的数据库。

## 桌面发布包

项目提供 Linux 和 Windows 的 PyInstaller、Nuitka 构建脚本。桌面发布包默认使用用户数据目录中的 SQLite，首次启动时会自动执行迁移，并在浏览器中打开本地工作台。

仓库同时提供 GitHub Actions 自动打包：可在 Actions 页面手动构建 Linux/Windows Artifact，推送 `v*` Tag 时会自动创建包含两个平台安装包的 GitHub Release。详细方式见 [docs/PACKAGING.md](docs/PACKAGING.md)。

## 项目结构

```text
src/dataset_builder/
├── application/       # 构建、审核、扩增、蒸馏、版本等应用服务
├── parsers/           # TXT、Markdown、JSON、JSONL、CSV 解析
├── splitters/         # 内容切分
├── generators/        # QA、Instruction、多轮生成
├── cleaners/          # 清洗与精确去重
├── validators/        # 统一 IR 与导出兼容性校验
├── formatters/        # Alpaca、ShareGPT 格式转换
├── exporters/         # JSON、JSONL 文件输出
├── training_targets/  # LLaMA-Factory 训练包
├── db/                # SQLAlchemy ORM 与会话
├── api.py             # FastAPI 入口
├── cli.py             # CLI 入口
└── desktop.py         # 桌面发布包入口
```

更多设计与进度信息：

- [产品需求](docs/PROJECT_SPEC.md)
- [架构设计](docs/ARCHITECTURE.md)
- [开发进度](docs/PROGRESS.md)
- [桌面打包](docs/PACKAGING.md)


## 安全提示

- 不要将 API Key、数据库密码或 `.env` 提交到 Git。
- 对外网开放服务前，请自行增加反向代理、访问控制和 HTTPS。本项目当前以个人部署和本地使用为主，不包含复杂多租户权限系统。
- 真实模型调用可能产生费用；建议先使用生成前预览和少量试生成确认配置。
