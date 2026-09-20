# 开发进度

## 当前阶段

已完成工程骨架、领域模型、数据库基础设施、TXT/Markdown 解析与基础切分、QA/Instruction 生成、基础清洗与校验，以及 Alpaca/ShareGPT JSON/JSONL 导出；尚未打通完整数据处理流程。

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

- 尚未实现 JSON、JSONL、CSV Parser。
- CLI 只有可运行的占位入口，尚无业务命令。
- 尚未实现 API 和 Web 页面。

## 已完成

- 基于已有的最小 uv 脚手架，修正 Python 要求为 3.12+，添加运行与开发依赖，并配置 ruff、pytest。
- 定义 SourceDocument、Chunk、Message、TrainingSample、ValidationIssue、PipelineRun、ExportRecord 的 Pydantic 模型和状态枚举。
- 建立领域模型单元测试，验证必填字段、消息角色、状态枚举与样本来源关联。
- 验证 CLI 占位入口可启动。
- `uv run ruff check .` 通过；`uv run pytest` 通过（4 个单元测试）。
- 配置 SQLAlchemy Async 会话、PostgreSQL ORM 映射、Alembic 异步迁移环境和初始迁移；数据库连接从环境变量读取。
- 建立数据库 Schema 单元测试与独立的 PostgreSQL 集成测试；Alembic 离线 SQL 生成通过。
- 本阶段 `uv run ruff check .` 通过；`uv run pytest` 为 6 通过、1 跳过（缺少 `TEST_DATABASE_URL`）。
- 已在本地 PostgreSQL `dataset_builder` 数据库上执行初始迁移；独立数据库往返集成测试通过（1 个测试，测试数据已回滚）。
- 提供本地连接后完整测试套件为 7 通过，`uv run ruff check .` 通过。
- 实现 TXT、Markdown Parser；Markdown 标题信息保留在文档元数据中，文件名、类型和字节大小可追踪。
- 实现固定长度、段落和 Markdown 标题切分，支持最大长度与可选重叠，并为 Chunk 记录顺序和来源信息。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 15 个测试通过。
- 实现 OpenAI Compatible 异步客户端、独立 LLM 接口与 QA Generator；支持模型配置、并发限制、超时、有限重试和 Pydantic 响应校验。
- 处理 Markdown 代码块包裹的 JSON、非法 JSON、缺失字段和空响应；使用 Fake Client/SDK 测试，不调用真实收费服务。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 27 个测试通过；SDK 客户端初始化与关闭验证通过。
- 实现 Instruction Generator，独立于 QA 策略生成 instruction/response 样本。
- 实现基础 Cleaner：文本首尾和 NFC 规范化、空内容与长度检查、项目范围内的内容哈希精确去重；被拒样本与问题记录均保留。
- 实现统一 IR 的消息结构、角色、顺序和目标格式兼容性校验；Alpaca 多轮或带 system 消息会生成明确问题。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 41 个测试通过。
- 实现独立于 ORM 的 Alpaca、ShareGPT Formatter；不兼容样本返回明确的 ValidationIssue，避免多轮消息被静默截断。
- 实现 JSON、JSONL 逐条写入与临时文件原子替换；PostgreSQL 导出服务分批读取，仅选择已审核、已校验且未删除的样本，并记录导出状态与数量。
- 使用真实 PostgreSQL 验证默认筛选和格式不兼容时旧文件保留，测试数据已回滚。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 48 个测试通过。

## 下一步任务

1. 打通 CLI 流程与样本审核能力。
2. 补充 JSON、JSONL、CSV 字段映射导入。
3. 后续增加 Web API 与页面。

## 进度维护规则

- Codex 每完成一个任务后更新“已完成”“当前未完成”和“下一步任务”。
- 新的关键架构决策记录在“已完成决策”。
- 不要把尚未实现的内容写成已完成。
- 记录测试和检查失败，不要隐瞒。
