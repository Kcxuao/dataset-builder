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
