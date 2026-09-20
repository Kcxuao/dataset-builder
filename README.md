# Dataset Builder

LLM 训练数据集构建工具，目前可通过 CLI 完成 TXT/Markdown 的构建、审核和导出流程。

## PostgreSQL 配置

使用 Python 3.12+ 和 uv。复制 `.env.example` 为 `.env`，设置指向 PostgreSQL 的 `DATABASE_URL`，格式为 `postgresql+asyncpg://user:password@host:port/database`。不要提交 `.env`。

```bash
uv sync
uv run alembic upgrade head
uv run dataset-builder --help
```

数据库集成测试需要独立的测试库：

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@host:port/test_database uv run pytest tests/integration
```

## LLM 配置

QA 和 Instruction Generator 使用 OpenAI Compatible Chat Completions API。`.env.example` 列出 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`、`LLM_TIMEOUT`、`LLM_CONCURRENCY_LIMIT` 和 `LLM_MAX_RETRIES`。本地无需认证的兼容服务可以省略 API Key。

## CLI 工作流

```bash
uv run dataset-builder build input.md --generator qa --project-name example
uv run dataset-builder list PROJECT_ID
uv run dataset-builder show SAMPLE_ID
uv run dataset-builder edit SAMPLE_ID --messages-file messages.json
uv run dataset-builder review SAMPLE_ID approved
uv run dataset-builder export PROJECT_ID --format sharegpt --output dataset.jsonl
```

`build` 输出项目和运行 ID。生成样本默认为待审核；`list` 和 `show` 显示来源 Chunk 与校验问题。编辑文件是消息数组，例如 `[{"role":"user","content":"问题"},{"role":"assistant","content":"答案"}]`。编辑后重新清洗、去重和校验，审核状态回到待审核。还可使用 `review SAMPLE_ID rejected`、`delete SAMPLE_ID`、`restore SAMPLE_ID`；Chunk 生成失败后用 `retry PROJECT_ID` 仅重试失败或未完成的 Chunk。导出只包含审核通过、校验通过且未软删除的样本。
