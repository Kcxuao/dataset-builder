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

QA 和 Instruction 生成器使用兼容接口。`.env.example` 列出模型地址、密钥、模型名称、温度、输出上限、超时、并发上限和重试次数。本地无需认证的兼容服务可以省略密钥。`LLM_CONCURRENCY_LIMIT` 控制同时进行的内容块模型请求数，修改后重启服务。对于支持 JSON 输出模式的服务，可设置 `LLM_JSON_MODE=true`；对于支持思考开关的 DeepSeek 服务，可设置 `LLM_THINKING=false`，避免短输出上限被思考内容耗尽。若出现输出截断提示，可提高 `LLM_MAX_TOKENS`。其他兼容服务不支持思考参数时，不要设置 `LLM_THINKING`。

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
uv run dataset-builder build articles.jsonl --content-field text --parser-workers 4
```

JSON 根节点可以是单个对象或对象数组。JSONL 每个非空行是一个对象。CSV 将选中的列按 `列名: 值` 拼成文档内容。缺失字段或非字符串内容会报错；每条结构化记录的行号或数组索引会保留在来源元数据中。

`--parser-workers` 和页面中的“解析工作线程数”可设为 1 到 16；结构化文件的独立记录及多个文档的切分可并行处理。单个 TXT 或 Markdown 文件本身只有一个解析任务，增加解析线程数不会加快该文件的读取；这类任务主要通过模型请求并发数加快生成阶段。

## Web 工作台与 API

完成数据库迁移和 LLM 配置后启动服务：

```bash
uv run uvicorn dataset_builder.api:app --host 127.0.0.1 --port 8000 --no-access-log --log-level warning
```

打开 `http://127.0.0.1:8000/` 导入文件、预览和编辑消息、审核样本并下载导出文件。API 文档位于 `/docs`。上传完成后会立即返回项目和运行 ID；页面每隔约一秒查询运行状态，显示处理阶段、内容块数量和失败详情。也可调用 `GET /api/runs/{run_id}` 查询进度。构建在 Web 服务进程内执行；服务中断后，已切分的任务可以重试剩余内容块，切分前中断则需要重新上传。导出文件默认保存在项目目录下的 `exports/`，该目录已被 Git 忽略。

工作台可新增并选择 OpenAI 兼容模型配置，分别设置接口地址、模型、密钥、输出参数和请求并发上限；未选择时仍使用 `.env` 中的默认模型。创建数据集时可选择问答或指令提示词预设，也可输入自定义提示词。所用模型和提示词会随构建记录保存，失败内容块重试时沿用。样本列表提供“本页通过、拒绝、待审核、删除、恢复”，每次只操作当前显示的样本；校验失败或已删除的样本会被跳过，不能批量通过。首次使用新版本前运行 `uv run alembic upgrade head`。
