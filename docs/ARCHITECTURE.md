# 架构设计说明

## 1. 总体架构

```text
Web UI / CLI
      ↓
FastAPI Routes / CLI Commands
      ↓
Application Services / Pipeline
      ↓
Domain Models + Core Interfaces
      ↓
Parser → Splitter → Generator / Augmentation → Cleaner → Validator
      ↓
Review
      ↓
Formatter → Exporter
      ↓
JSON / JSONL
```

PostgreSQL 用于保存项目、源文档、Chunk、训练样本、校验问题、Pipeline 状态和导出记录。原始上传文件和导出文件可以存放在文件系统，数据库保存路径、元数据和状态。

## 2. 推荐目录结构

```text
src/dataset_builder/
├── api/                 # FastAPI 路由、依赖注入和响应模型
├── application/         # 应用服务和用例
├── models/              # 领域模型与枚举
├── parsers/             # TXT、Markdown、JSON、JSONL、CSV
├── splitters/           # 固定长度、段落、Markdown 标题
├── generators/          # QA、Instruction
├── cleaners/            # 空数据、规范化、长度、精确去重
├── validators/          # IR 与目标格式校验
├── formatters/          # Alpaca、ShareGPT
├── exporters/           # JSON、JSONL
├── pipeline/            # 流程编排、进度和恢复
├── llm/                 # OpenAI Compatible Client
├── storage/             # SQLAlchemy Repository 与文件存储
├── db/                  # ORM、Session、Alembic 集成
├── cli/                 # CLI 入口
├── config.py            # Pydantic Settings
└── main.py              # FastAPI 应用创建

tests/
├── unit/
├── integration/
└── fixtures/
```

## 3. 核心接口

核心模块使用 Protocol 或抽象基类定义稳定边界，MVP 不需要复杂插件框架。

```python
class Parser(Protocol):
    def parse(self, source: ImportSource) -> list[SourceDocument]: ...


class Splitter(Protocol):
    def split(self, document: SourceDocument) -> list[Chunk]: ...


class Generator(Protocol):
    async def generate(self, chunk: Chunk) -> list[TrainingSample]: ...


class Cleaner(Protocol):
    def clean(self, samples: list[TrainingSample]) -> CleanResult: ...


class Validator(Protocol):
    def validate(self, sample: TrainingSample) -> list[ValidationIssue]: ...


class Formatter(Protocol):
    def format(self, sample: TrainingSample) -> dict[str, object]: ...
```

## 4. 领域模型

### SourceDocument

- id
- project_id
- source_name
- source_type
- content
- metadata
- parse_status
- created_at

### Chunk

- id
- document_id
- index
- content
- content_hash
- metadata
- generation_status
- created_at

### TrainingSample

- id
- project_id
- document_id
- chunk_id
- messages
- metadata
- content_hash
- review_status
- validation_status
- is_deleted
- created_at
- updated_at
- parent_sample_id（扩增样本的父样本，可空）
- generation_run_id（生成或扩增任务，可空）

### AugmentationJob

- run_id
- seed_sample_id
- strategy
- round
- status
- generated_count
- error_message

扩增由独立应用服务编排，不改变原始文件构建链路。每个 Job 只扩增一个已通过种子样本，任务可在失败后仅重试未完成 Job；结果通过统一 Cleaner 和 Validator 后才作为待审核样本写入。

### ValidationIssue

- id
- sample_id
- rule
- severity
- message
- created_at

### PipelineRun

- id
- project_id
- status
- current_stage
- configuration
- total_items
- completed_items
- failed_items
- error_message
- started_at
- finished_at

### ExportRecord

- id
- project_id
- format
- file_type
- status
- sample_count
- file_path
- error_message
- created_at
- finished_at

## 5. PostgreSQL 设计原则

- `messages` 和 `metadata` 可以使用 JSONB。
- `project_id`、`chunk_id`、状态、时间等查询字段使用独立列。
- 为项目筛选、审核状态、校验状态和软删除字段建立合适索引。
- `content_hash` 用于精确重复检测，可结合项目范围建立唯一或普通索引。
- 使用 Alembic 管理全部结构变化。
- Repository 返回领域对象或专用 DTO，不向 Formatter 暴露 ORM 细节。

## 6. Pipeline 设计

Pipeline 只负责编排，不承担具体解析、生成或格式转换细节。

```text
CREATED
  → IMPORTING
  → PARSING
  → SPLITTING
  → GENERATING
  → CLEANING
  → VALIDATING
  → READY_FOR_REVIEW
  → COMPLETED
```

失败状态需要记录失败阶段和错误原因。生成阶段按 Chunk 保存进度，任务重新执行时跳过已成功生成且配置未变化的 Chunk。

MVP 使用 asyncio 并发控制即可，不引入 Celery 和 Redis。

## 7. LLM 设计

```python
class LLMClient(Protocol):
    async def generate(self, messages: list[Message], response_model: type[T]) -> T: ...
```

`OpenAICompatibleClient` 实现协议。`QAGenerator` 和 `InstructionGenerator` 依赖 LLMClient，而不是依赖 OpenAI SDK 的具体响应对象。

测试时使用 `FakeLLMClient` 返回固定结果，不调用真实服务。

## 8. Review 设计

审核状态建议：

```text
PENDING
APPROVED
REJECTED
```

用户编辑样本后：

1. 更新统一 IR。
2. 重新计算 content_hash。
3. 清除旧的校验结论。
4. 重新执行 Validator。
5. 根据产品规则决定是否恢复为 PENDING。

## 9. 导出设计

导出流程：

```text
按条件查询 TrainingSample
        ↓
流式/分批读取
        ↓
Formatter 转换
        ↓
Exporter 逐条写入
        ↓
生成文件并保存 ExportRecord
```

JSONL 最适合大数据集。JSON 数组导出也应避免无界内存占用，可以先写 `[`，逐项写入并维护逗号，最后写 `]`。

## 10. 第一阶段实施顺序

1. 初始化 uv 项目、ruff 和 pytest。
2. 建立领域模型和枚举。
3. 配置 PostgreSQL、SQLAlchemy 与 Alembic。
4. 实现 TXT/Markdown Parser。
5. 实现基础 Splitter。
6. 实现 OpenAI Compatible Client 和 QA Generator。
7. 实现 Cleaner、Validator 和精确去重。
8. 实现 Alpaca、ShareGPT Formatter。
9. 实现 JSON、JSONL Exporter。
10. 用 CLI 打通完整垂直流程。
11. 增加项目、样本 Review API。
12. 增加 Web 页面。
13. 补充 JSON、JSONL、CSV 字段映射导入。
