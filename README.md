# Dataset Builder

LLM 训练数据集构建工具，可通过 CLI 或 Web 工作台完成 TXT、Markdown、JSON、JSONL、CSV 的构建、审核和导出流程。

## 数据库配置

使用 Python 3.12+ 和 uv。复制 `.env.example` 为 `.env`，不要提交 `.env`。

- 标准部署使用 `DATABASE_PROVIDER=postgresql` 和 `DATABASE_URL=postgresql+asyncpg://user:password@host:port/database`。
- 本地单机使用 `DATABASE_PROVIDER=sqlite` 与可选的 `SQLITE_PATH=./dataset-builder.sqlite3`；SQLite 会开启外键、WAL 和写入等待，但不支持多服务进程同时写入。
- 切换后端不会迁移已有数据；请通过导出和导入迁移数据。修改后端后重启服务，再执行迁移。

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

前端使用 pnpm、Vue 和 Element Plus。首次启动或前端代码变更后，先构建静态资源：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
```

完成数据库迁移、LLM 配置和前端构建后启动服务：

```bash
uv run uvicorn dataset_builder.api:app --host 127.0.0.1 --port 8000 --no-access-log --log-level warning
```

打开 `http://127.0.0.1:8000/` 导入文件、预览和编辑消息、审核样本并下载导出文件。API 文档位于 `/docs`。上传完成后会立即返回项目和运行 ID；页面每隔约一秒查询运行状态，显示处理阶段、内容块数量和失败详情。也可调用 `GET /api/runs/{run_id}` 查询进度。构建在 Web 服务进程内执行；服务中断后，已切分的任务可以重试剩余内容块，切分前中断则需要重新上传。导出文件默认保存在项目目录下的 `exports/`，该目录已被 Git 忽略。

样本列表提供“本页通过、拒绝、待审核、删除、恢复”，每次只操作当前显示的样本；校验失败或已删除的样本会被跳过，不能批量通过。

工作台侧边栏现提供独立的“模型配置”“提示词配置”“处理设置”和“回收站”。模型可新增、编辑、归档并设置默认值；编辑后的旧版本保留供历史任务重试。提示词可从内置预设选择，也可创建和管理自定义模板。解析线程数在处理设置中统一设定，模型请求并发上限按模型设定。创建数据集时只需选择模型和提示词；处理设置会自动用于新任务。项目可移入回收站并恢复，来源、样本和导出记录均保留。升级数据库请运行 `uv run alembic upgrade head`。

新增或编辑模型时，可选择阿里云百炼（Qwen）、DeepSeek、智谱 AI、MiniMax 或自定义兼容服务，预设会填入名称和接口地址。填写地址和 API Key 后点击“拉取模型”，页面会通过后端请求该服务的标准 `GET /models` 接口供选择；服务不支持该接口时可继续手动填写模型名称。编辑配置时若修改接口地址，拉取前需要重新填写 API Key。

模型配置页会在打开时检查每个已启用配置的标准 `GET /models` 接口，并在卡片上显示连接状态；可使用“刷新状态”或单卡“刷新连接”再次检查。该检查不调用模型生成接口，也不消耗生成额度。
