# 开发进度

## 当前阶段

已完成首阶段工程骨架与领域模型，尚未实现数据处理流程。

## 已完成决策

- 项目定位为完整的 LLM Dataset Builder，而不是单纯格式转换器。
- 技术栈使用 Python 3.12+、uv、FastAPI、Pydantic、PostgreSQL、SQLAlchemy Async、asyncpg、Alembic、pytest 和 ruff。
- PostgreSQL 为主要数据库。
- 使用 `SourceDocument → Chunk → TrainingSample` 三层数据结构。
- `TrainingSample.messages` 为统一 IR。
- Alpaca 和 ShareGPT 只在导出时动态转换，不作为数据库标准格式。
- 第一阶段支持 JSON 和 JSONL 导出。
- 大数据集使用流式或分批查询与逐条写入。
- 核心模块与 FastAPI 解耦，CLI 与 Web 复用同一套能力。
- MVP 不实现 RAG、向量数据库、LoRA、模型训练和 Agent。

## 当前未完成

- 尚未配置数据库与 Alembic。
- 尚未实现 Parser、Splitter、Generator、Cleaner、Validator、Formatter 和 Exporter。
- CLI 只有可运行的占位入口，尚无业务命令。
- 尚未实现 API 和 Web 页面。
- 尚未建立 PostgreSQL 集成测试。

## 已完成

- 基于已有的最小 uv 脚手架，修正 Python 要求为 3.12+，添加运行与开发依赖，并配置 ruff、pytest。
- 定义 SourceDocument、Chunk、Message、TrainingSample、ValidationIssue、PipelineRun、ExportRecord 的 Pydantic 模型和状态枚举。
- 建立领域模型单元测试，验证必填字段、消息角色、状态枚举与样本来源关联。
- 验证 CLI 占位入口可启动。
- `uv run ruff check .` 通过；`uv run pytest` 通过（4 个单元测试）。

## 下一步任务

1. 配置 PostgreSQL、SQLAlchemy Async 与 Alembic，并建立独立的集成测试。
2. 实现 TXT、Markdown Parser 和基础 Splitter。
3. 在后续阶段逐步打通生成、清洗、校验与导出流程。

## 进度维护规则

- Codex 每完成一个任务后更新“已完成”“当前未完成”和“下一步任务”。
- 新的关键架构决策记录在“已完成决策”。
- 不要把尚未实现的内容写成已完成。
- 记录测试和检查失败，不要隐瞒。
