# Dataset Builder

LLM 训练数据集构建工具，目前处于工程基础设施阶段。

## PostgreSQL 配置

使用 Python 3.12+ 和 uv。复制 `.env.example` 为 `.env`，设置指向 PostgreSQL 的 `DATABASE_URL`，格式为 `postgresql+asyncpg://user:password@host:port/database`。不要提交 `.env`。

```bash
uv sync
uv run alembic upgrade head
uv run dataset-builder
```

`dataset-builder` 目前只有占位入口。数据库集成测试需要独立的测试库：

```bash
TEST_DATABASE_URL=postgresql+asyncpg://user:password@host:port/test_database uv run pytest tests/integration
```

## LLM 配置

QA Generator 使用 OpenAI Compatible Chat Completions API。`.env.example` 列出 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`、`LLM_TIMEOUT`、`LLM_CONCURRENCY_LIMIT` 和 `LLM_MAX_RETRIES`。本地无需认证的兼容服务可以省略 API Key。当前尚未提供调用 Generator 的 CLI 命令。
