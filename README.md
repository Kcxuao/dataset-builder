# Dataset Builder

LLM 训练数据集构建工具，可通过 CLI 或 Web 工作台完成 TXT、Markdown、JSON、JSONL、CSV 的构建、审核和导出流程。

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

JSON 和 JSONL 导入需显式选择内容字段，支持用点号指定嵌套对象字段；CSV 导入需指定一个或多个内容列：

```bash
uv run dataset-builder build articles.json --content-field article.body
uv run dataset-builder build articles.jsonl --content-field text
uv run dataset-builder build articles.csv --content-column title --content-column body
```

JSON 根节点可以是单个对象或对象数组。JSONL 每个非空行是一个对象。CSV 将选中的列按 `列名: 值` 拼成文档内容。缺失字段或非字符串内容会报错；每条结构化记录的行号或数组索引会保留在来源元数据中。

## Web 工作台与 API

完成数据库迁移和 LLM 配置后启动服务：

```bash
uv run uvicorn dataset_builder.api:app --host 127.0.0.1 --port 8000 --no-access-log --log-level warning
```

打开 `http://127.0.0.1:8000/` 导入文件、预览和编辑消息、审核样本并下载导出文件。API 文档位于 `/docs`。上传完成后会立即返回项目和运行 ID；页面每隔约一秒查询运行状态，显示处理阶段、内容块数量和失败详情。也可调用 `GET /api/runs/{run_id}` 查询进度。构建在 Web 服务进程内执行；服务中断后，已切分的任务可以重试剩余内容块，切分前中断则需要重新上传。导出文件默认保存在项目目录下的 `exports/`，该目录已被 Git 忽略。
