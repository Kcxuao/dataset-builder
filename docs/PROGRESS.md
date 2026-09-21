# 开发进度

## 当前阶段

已通过 CLI 和 Web API/页面打通 TXT、Markdown、JSON、JSONL、CSV 构建、生成、清洗、校验、人工审核与 Alpaca/ShareGPT JSON/JSONL 导出流程。

第三阶段“零模型调用的质量概览”已完成：项目页按需读取数据库统计，不调用模型；第二阶段的筛选与定向重生成作为既有基础继续保留。

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

- MVP 核心流程已实现；Vue 页面已完成一轮可读性与任务流程精修，待浏览器人工验收和真实 LLM 服务验收。

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
- 实现共用应用服务与 CLI 命令：构建、失败 Chunk 重试、样本查看/编辑、审核、软删除/恢复和导出。
- 构建任务按 Chunk 保存进度；单 Chunk 调用失败时记录错误并继续，重试时跳过成功 Chunk 且校验 LLM 配置一致。
- 编辑后重新规范化、计算哈希和校验，并恢复待审核状态；导出仍只包含审核及校验通过的非删除样本。
- Fake LLM 与真实 PostgreSQL 的往返测试覆盖构建、失败继续、重试、审核、编辑和导出。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 49 个测试通过。
- 实现 JSON、JSONL、CSV Parser；JSON/JSONL 支持显式内容字段及嵌套对象路径，CSV 支持选择多个内容列。
- 扩展 CLI 构建选项与来源元数据，保留结构化记录的数组索引或文件行号；字段缺失和不适合的内容类型给出明确错误。
- Fake LLM 与真实 PostgreSQL 测试覆盖三种结构化文件从导入到样本预览的流程。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 61 个测试通过。
- 增加 FastAPI Web API 与静态工作台，支持文件上传构建、项目与样本查看、编辑、审核、软删除、失败 Chunk 重试及导出下载；API 复用现有应用服务。
- 新增 Fake LLM 与 PostgreSQL API 往返集成测试，覆盖上传、审核、编辑、导出、下载和静态页面；测试数据通过外层事务回滚。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 62 个测试通过；wheel 构建及静态资源打包检查通过。
- Web 构建请求改为先返回项目和运行 ID，再在服务进程内执行；提供运行进度查询，页面显示阶段、成功/失败内容块数与错误详情，并自动轮询。处理阶段和每块结果输出中文日志。
- 使用暂停中的 Fake LLM 与独立 PostgreSQL 连接验证：模型等待期间可以查询到“生成中”和当前内容块进度；服务中断后的任务可识别为中断状态。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 64 个测试通过；前端脚本语法检查通过。
- 增加可选模型 JSON 输出模式与思考开关，区分空正文、结构不符和输出截断，错误提示改为中文；本地 DeepSeek 开发配置已启用 JSON 模式并关闭思考。
- 结构化记录解析和多文档切分支持可配置的工作线程数；内容块模型请求按并发上限批量并行，结果按原顺序清洗、去重和入库。处理日志记录各阶段耗时。
- 本阶段 `uv run ruff check .` 通过；完整测试套件连接本地 PostgreSQL 后 75 个测试通过，均使用模拟模型。
- 新增数据库模型配置与 Web 新增、选择入口，支持 OpenAI 兼容地址、模型和生成参数；默认环境模型继续可选，接口列表不返回密钥。
- QA 与 Instruction 各提供三种提示词预设，并支持自定义提示词；构建记录保存最终提示词，重试沿用原配置。
- 样本列表增加本页批量通过、拒绝、待审核、软删除与恢复；无效样本不会被批量通过。
- 本阶段 `uv run ruff check .`、前端语法检查通过；完整测试套件连接本地 PostgreSQL 后 79 个测试通过。
- 将模型、提示词和解析线程数移至独立配置菜单；模型编辑保存历史版本以支持原任务重试，可归档并设置默认模型。
- 新增自定义提示词模板管理、工作区处理默认设置，以及数据集回收站与恢复；回收站项目不可审核、重试或导出。
- 本阶段 `uv run ruff check .`、前端语法检查通过；连接本地 PostgreSQL 的完整测试套件 79 个测试通过。
- Vue 工作台沿用深蓝侧栏和 Element Plus，调整创建表单的文件类型字段、构建进度与审核反馈、移动端导航和文字层级；修正 Vite 自动导入配置，并补充 pnpm 构建说明及静态资源集成断言。
- `pnpm build`、`uv run ruff check .` 通过；纯单元测试 69 个通过。`test_api_config.py` 在当前沙箱中卡住，未计入通过结果；Playwright MCP 因缺少 Chrome 未能完成浏览器验收。Vite 仍提示主脚本超过 500 kB。
- 新开发测试库 `deb.lan:5432/dataset_builder` 已通过 Alembic 从空版本迁移至 `0003 (head)`，再次读取版本确认成功。
- 模型配置增加阿里云百炼（Qwen）、DeepSeek、智谱 AI、MiniMax 和自定义服务预设；填写地址与 API Key 后可由后端调用标准 `GET /models` 拉取可选模型，仍支持手动输入。编辑时地址变更不会复用旧 API Key。
- 本阶段 `uv run ruff check .` 通过；新增模型发现与地址变更密钥保护测试，排除当前沙箱中卡住的 `test_api_config.py` 后，测试套件为 74 通过、9 跳过；`pnpm build` 通过。
- 模型卡片增加连接状态灯和刷新操作；后端批量调用已保存配置的标准 `GET /models` 检查地址、密钥和当前模型是否可见，不调用模型生成接口，也不记录检查结果到数据库。
- 本阶段 `uv run ruff check .`、`pnpm build` 通过；新增连接状态单元测试后，排除当前沙箱中卡住的 `test_api_config.py`，测试套件为 76 通过、9 跳过。
- 完成迭代第一阶段“生成前预览与少量试生成”：新增预览与试生成 API，复用正式 Parser、Splitter、Generator、Cleaner、Validator；预览不创建项目、不写数据库、不调用模型，试生成限制为 1 至 3 个内容块且结果不入库。
- 预览使用文件内容与解析、切分、提示词、模型配置指纹；试生成会重新解析并核对指纹，文件或配置变更后拒绝使用旧预览。工作台在文件或配置变化时清除旧结果，并展示前 20 个 Chunk、长度和模型请求量上界。
- 识别兼容服务返回的额度不足错误，停止未开始的后续请求并保留已完成结果；普通限流仍按既有有限重试执行。
- 新增 API 回归测试覆盖预览顺序、无项目写入、最多 3 个内容块和失效指纹；`pnpm build`、`uv run ruff check .` 通过，完整测试套件为 78 通过、9 跳过（未配置独立 PostgreSQL 测试库）。
- 重做生成前预览与试生成结果的工作台呈现：内容块改为可滚动的选择卡片，长文本限行预览；临时样本按角色展示，避免原始长文本撑破页面。`pnpm build` 通过。
- 生成前预览调整为独立的构建前检查 Dialog：创建表单保持简洁，Dialog 内集中完成切分查看、内容块选择和试生成结果检查；配置变化会自动关闭并清除旧预览。`pnpm build` 通过。
- 完成质量概览：新增 `GET /api/projects/{id}/quality-summary`，统计 Chunk 状态、审核与校验状态、常见问题、精确重复、消息长度、来源占比及可导出数量；默认排除已删除和已替代样本，且不创建或调用模型客户端。项目页新增数据概览面板。`uv run ruff check src/dataset_builder`、`pnpm build` 通过。

## 下一步任务

1. 实施迭代第二阶段：筛选审核与定向重生成。
2. 在具备浏览器的环境中验收桌面与手机布局、键盘操作和完整构建流程，修复验收中发现的问题。
3. 使用现有额度对实际兼容 LLM 服务验收；额度用尽时停止调用，不使用重置卡。

## 进度维护规则

- Codex 每完成一个任务后更新“已完成”“当前未完成”和“下一步任务”。
- 新的关键架构决策记录在“已完成决策”。
- 不要把尚未实现的内容写成已完成。
- 记录测试和检查失败，不要隐瞒。
