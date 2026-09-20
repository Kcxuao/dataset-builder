# AGENTS.md

## 项目定位

本项目是一个轻量、模块化、可扩展的 LLM 训练数据集构建工具（Dataset Builder）。它将用户提供的原始数据自动导入、解析、切分、生成、清洗、校验和审核，最终导出成可直接用于大模型训练的数据集。

本项目不是简单的 Alpaca/ShareGPT JSON 字段转换器，而是一套完整的数据集构建流程。

开始设计或实现功能前，必须先阅读以下文件：

- `docs/PROJECT_SPEC.md`：完整产品需求和 MVP 边界，是产品需求的权威来源。
- `docs/ARCHITECTURE.md`：模块划分、核心数据模型和依赖方向。
- `docs/PROGRESS.md`：当前进度、已完成内容、待办事项和已确定决策。

如果代码实现与文档冲突，先向用户说明冲突，不要自行扩大或改变需求。

## 技术栈

- Python 3.12+
- uv：统一负责项目初始化、依赖管理和命令运行
- FastAPI
- Pydantic
- SQLAlchemy 2.0 Async
- PostgreSQL
- asyncpg
- Alembic
- pytest、pytest-asyncio
- ruff

统一使用以下方式管理项目：

```bash
uv init
uv add ...
uv sync
uv run ...
```

不要将 `pip + requirements.txt` 作为主要依赖管理方式。除非用户明确要求，否则不要引入 Poetry、PDM、Conda 等其他包管理方案。

## MVP 范围

第一阶段必须实现：

- TXT、Markdown、JSON、JSONL、CSV 文件导入。
- 将导入内容解析成统一的内部对象。
- 文档内容切分为 Chunk。
- 通过 OpenAI Compatible API 自动生成 QA 和 Instruction 训练样本。
- 空数据过滤、基础文本规范化和长度检查。
- 精确重复检测与去重。
- Message Role、消息顺序和数据结构校验。
- 生成结果预览和人工编辑。
- Alpaca、ShareGPT 格式导出。
- JSON、JSONL 文件导出。
- CLI 与 Web API 复用同一套核心能力。

第一阶段明确不做：

- RAG。
- 向量数据库。
- LoRA。
- 模型训练。
- Agent。
- 分布式任务系统。
- 复杂插件市场。
- 语义向量去重。
- 复杂多租户和权限系统。

不要擅自实现 MVP 之外的功能。

## 核心处理流程

```text
原始数据
   ↓
Import 数据导入
   ↓
Parse 内容解析
   ↓
Split 内容切分
   ↓
Generate LLM 自动生成训练样本
   ↓
Clean 数据清洗
   ↓
Validate 数据校验
   ↓
Review 预览/人工修改
   ↓
Export 数据集导出
```

## 架构原则

核心能力必须和 FastAPI 解耦。FastAPI API、CLI 和未来其他入口必须调用相同的应用服务与核心模块，不允许把 Parser、Generator、Validator、Formatter 等业务逻辑直接写进 API 路由函数。

核心模块至少包括：

- Parser
- Splitter
- Generator
- Cleaner
- Validator
- Formatter
- Exporter
- Pipeline
- Storage
- API
- CLI

推荐依赖方向：

```text
API / CLI
    ↓
Application / Pipeline
    ↓
Domain Models + Core Interfaces
    ↓
Parsers / Splitters / Generators / Cleaners / Validators
    ↓
Infrastructure：PostgreSQL / LLM Client / File Export
```

不要让 Core 依赖 FastAPI，也不要让 Formatter 依赖数据库 ORM 模型。

## 统一内部表示 IR

数据库中不能将 Alpaca 或 ShareGPT 作为唯一标准格式。训练样本必须使用统一 IR，Alpaca 和 ShareGPT 只在导出阶段由 Formatter 转换。

核心对象至少包括：

- `SourceDocument`：导入并解析后的源文档。
- `Chunk`：由源文档切分得到的内容块。
- `Message`：一条 system、user 或 assistant 消息。
- `TrainingSample`：统一训练样本 IR。
- `ValidationIssue`：样本校验问题。
- `PipelineRun`：Pipeline 执行记录与状态。
- `ExportRecord`：导出记录。

训练样本的语义结构：

```json
{
  "id": "sample_xxx",
  "messages": [
    {"role": "system", "content": "你是一个专业助手"},
    {"role": "user", "content": "问题"},
    {"role": "assistant", "content": "答案"}
  ],
  "metadata": {
    "source_name": "example.md",
    "source_type": "markdown",
    "chunk_id": "chunk_xxx"
  }
}
```

`system` 信息统一放入 `messages`，不要再建立语义重复的顶层 `system` 字段。必须保留 TrainingSample → Chunk → SourceDocument 的数据血缘。

PostgreSQL 中可使用 JSONB 保存 `messages` 和 `metadata`，但重要的查询字段、关联字段和状态字段必须使用独立列。

## LLM 集成要求

LLM 层优先兼容 OpenAI Compatible API，使其可以连接 OpenAI、Qwen、DeepSeek、vLLM、Ollama 等兼容服务。

配置至少支持：

- base URL
- API Key
- model
- temperature
- max tokens
- timeout
- concurrency limit

Generator 只能依赖抽象的 LLM Client 接口，不得与具体模型提供商绑定。QA 与 Instruction 应作为独立生成策略。

LLM 返回结果必须经过 Pydantic 校验，并处理：

- Markdown 代码块包裹的 JSON。
- 非法或残缺 JSON。
- 字段缺失。
- 超时与有限次数重试。
- 单个 Chunk 失败但整个任务可继续。

不得将 API Key、数据库密码或其他密钥提交到 Git。

## 清洗与校验要求

MVP 清洗至少包含：

- 空内容过滤。
- 首尾空白处理。
- 基础长度检查。
- 基于规范化内容哈希的精确去重。

MVP 校验至少包含：

- messages 不为空。
- role 只能是 system、user、assistant。
- user 和 assistant 的基本顺序正确。
- content 不能为空。
- 导出目标格式能够无损表达当前样本。

校验失败应生成明确的 `ValidationIssue`，不能静默丢弃数据。

## Formatter 与 Exporter

Formatter 负责把统一 IR 转成目标训练格式，Exporter 负责写出文件，两者必须分离。

第一阶段 Formatter：

- Alpaca Formatter
- ShareGPT Formatter

第一阶段 Exporter：

- JSON Exporter
- JSONL Exporter

数据库中不要同时保存一份 Alpaca 和一份 ShareGPT 数据。用户修改 IR 后，应在导出时动态生成目标格式。

JSONL 导出必须采用 PostgreSQL 流式或分批查询，并逐行写入文件，禁止一次性将完整数据集加载到内存。

默认只导出满足以下条件的样本：

- 校验通过。
- 人工审核通过。
- 未被软删除。

如果 IR 中存在 Alpaca 无法无损表达的多轮对话，应返回明确错误或校验问题，不得静默截断消息。

## 数据库规则

- 使用 PostgreSQL。
- 使用 SQLAlchemy 2.0 Async 与 asyncpg。
- 使用 Alembic 管理数据库迁移。
- 时间统一使用 UTC。
- ID 优先使用 UUID 或 ULID。
- 不在数据库触发器中放置核心业务逻辑。
- 不在 ORM 模型上堆积 Pipeline、Formatter 等业务逻辑。

## 编码与测试规则

- 优先使用直接、清楚的代码，不要过早设计复杂插件系统。
- 公共函数和方法必须有类型标注。
- 模块保持单一职责。
- 修改行为时必须新增或更新测试。
- 测试不得依赖真实收费 LLM API，使用 Fake 或 Mock LLM Client。
- PostgreSQL 集成测试与纯单元测试应分开。
- 不要为了视觉排版随意拆分较短的函数签名、调用或赋值语句。
- 不要修改与当前任务无关的文件。

实现完成后运行：

```bash
uv run ruff check .
uv run pytest
```

## 工作流程

处理较大任务前必须：

1. 检查当前仓库结构和已有代码。
2. 阅读本文件以及 `docs/PROJECT_SPEC.md`、`docs/ARCHITECTURE.md`、`docs/PROGRESS.md`。
3. 简要说明准备修改的范围。
4. 只实现用户当前要求，不主动扩大范围。
5. 完成后运行相关测试和 ruff。
6. 如完成一个里程碑，更新 `docs/PROGRESS.md`。
7. 汇报修改文件、验证结果和仍未解决的问题。

当需求存在会明显影响架构的歧义时，先询问用户；普通实现细节可以做合理选择并在结果中说明。
