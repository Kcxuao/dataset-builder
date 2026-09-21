# LLM Dataset Builder 产品需求说明

## 1. 项目定位

开发一个轻量级的 LLM 训练数据集构建工具或网站，核心目标是将用户提供的原始数据自动解析、结构化、清洗并转换成可以直接用于大模型训练的数据集。

它不是单纯的 Alpaca/ShareGPT JSON 转换器，而是完整的 Dataset Builder。

一句话概括：使用 Python、uv、PostgreSQL 或本地 SQLite 开发一个轻量、模块化、可扩展的 LLM Dataset Builder，把各种原始数据自动处理成 Alpaca、ShareGPT 等可直接训练的结构化数据集。

## 2. 目标用户

- 需要将文档转成监督微调数据的个人开发者。
- 需要构建 QA 或 Instruction 数据集的模型使用者。
- 使用 OpenAI、Qwen、DeepSeek、vLLM、Ollama 等模型服务生成训练样本的用户。

MVP 以单用户、个人部署和本地开发为主，不提前实现复杂多租户和企业权限体系。

## 3. 核心流程

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

## 4. MVP 功能范围

### 4.0 本轮迭代：生成前预览与少量试生成

在不改变既有“导入→生成→审核→导出”主链路的前提下，本轮先交付生成前预览：用户上传文件并设置解析、切分、提示词和模型后，可查看文档数、Chunk 总数、前 20 个 Chunk 及长度；可显式选择最多 3 个 Chunk 进行临时试生成，并查看样本和校验问题后再启动完整构建。预览和试生成均不创建项目或写入数据库；预览不调用模型。预览响应会给出文件与配置指纹，试生成必须携带该指纹并在服务端重新核对。请求量仅按 Chunk 数及模型输出上限提示上界，不承诺准确费用。

本轮继续实现筛选审核与定向重生成：样本列表支持按审核、校验、删除状态、来源、问题规则和关键词分页筛选；可按原构建任务的模型、提示词和生成方式重生成单个 Chunk。重生成成功且至少一条新样本通过结构校验时，旧样本才标记为已替代；默认列表和导出排除已替代样本。

本轮增加零模型调用的质量概览：项目页按需读取 Chunk 状态、样本审核和校验状态、常见问题、精确重复、消息长度、来源占比与可导出数量。统计默认排除已删除和已替代样本，页面明确标注口径。

本轮实现批量导入：多个原始来源文件在一个项目下分别保留文档血缘；并支持将 Alpaca、ShareGPT 的 JSON/JSONL 转换为统一 IR，保留文件名与行号，重新清洗、校验并以待审核状态保存。

本轮增加多维数据集扩增：仅以审核和校验均通过的样本为种子，支持按来源与关键词筛选，并按表达改写、认知角度、难度深化、角色视角、场景应用等策略扩增。用户可选择扩增提示词模板或临时自定义提示词，先查看不调用模型的种子和策略分配预览，再创建可恢复的后台扩增任务。扩增结果保留父样本、Chunk、来源文档与运行记录血缘，统一进入待审核状态；精确重复或校验失败时在目标数量两倍的最大尝试次数内补生。

本轮增加教师答案蒸馏：仅选择审核和校验均通过、未删除且未替代的训练样本。教师模型不接收旧 assistant 内容，根据来源及原 system/user 独立作答；多轮样本逐轮生成，并使用新教师回答作为后续上下文。候选样本通过统一清洗和校验后进入待审核，经人工审核通过时才将原样本标记为已替代。系统保留候选→原样本→Chunk→来源文档以及 Job、运行、提示词与模型快照血缘。蒸馏不使用 logits 或概率分布，也不增加裁判模型调用。

### 4.1 文件导入

第一阶段支持：

- TXT
- Markdown
- JSON
- JSONL
- CSV

导入后需要记录原始文件名、文件类型、大小、导入时间、解析状态以及必要的来源元数据。

### 4.2 内容解析

Parser 将不同格式的数据转换成统一的 `SourceDocument`。

- TXT：按文本内容读取。
- Markdown：保留标题等可供切分使用的结构信息。
- JSON/JSONL：允许配置或选择内容字段，不假定所有输入都有相同 Schema。
- CSV：允许选择参与构建内容的列。

Parser 不直接生成 Alpaca 或 ShareGPT 数据。

### 4.3 内容切分

Splitter 将 SourceDocument 转换为 Chunk。MVP 至少支持：

- 固定长度切分。
- 按段落切分。
- Markdown 标题层级切分。
- Chunk 最大长度限制。
- 可选重叠长度。

每个 Chunk 必须保留所属 SourceDocument、顺序编号和来源信息。

### 4.4 LLM 样本生成

第一阶段提供两种生成模式：

- QA：根据 Chunk 生成一个或多个问题与答案。
- Instruction：根据 Chunk 生成指令与回答。

LLM 接口必须兼容 OpenAI Compatible API。不同模型之间通过配置切换，不将 Generator 与具体厂商绑定。

应支持并发限制、超时、有限重试、错误记录和单 Chunk 重试。一个 Chunk 失败不应导致已完成结果丢失。

### 4.5 数据清洗

MVP 清洗能力：

- 空样本过滤。
- 空消息过滤或错误标记。
- 文本首尾空白规范化。
- 长度检查。
- 基于规范化内容哈希的精确重复检测和去重。

近似或语义去重不属于第一阶段。

### 4.6 数据校验

MVP 校验能力：

- TrainingSample 结构校验。
- Message Role 校验。
- Message Content 非空校验。
- 基本对话顺序校验。
- 目标 Formatter 兼容性校验。

校验结果需要包含问题类型、严重程度、说明以及关联样本。错误数据不能被无提示地删除。

### 4.7 Review 与人工编辑

用户可以：

- 查看生成的样本列表。
- 查看样本关联的原始 Chunk。
- 查看校验问题。
- 编辑 system、user、assistant 消息内容。
- 将样本标记为通过、拒绝或待审核。
- 删除或恢复样本。

编辑后必须重新计算用于去重的内容哈希，并重新校验。

### 4.8 数据集导出

第一阶段支持：

- Alpaca JSON
- Alpaca JSONL
- ShareGPT JSON
- ShareGPT JSONL

默认只导出：

- 审核通过。
- 校验通过。
- 未删除。

JSONL 必须流式或分批导出，避免将完整数据集一次性加载到内存。导出记录至少包含项目、格式、文件类型、样本数量、创建时间和导出状态。

## 5. 统一 IR

内部不能直接绑定 Alpaca 或 ShareGPT。推荐 IR：

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
    "chunk_id": "chunk_xxx",
    "generator": "qwen"
  }
}
```

内部对象分为三层：

```text
SourceDocument → Chunk → TrainingSample
```

这样可以定位每条训练样本来自哪个文件和哪个 Chunk，并记录生成模型与相关信息。

## 6. 格式转换规则

### 6.1 Alpaca

典型输出：

```json
{
  "instruction": "问题",
  "input": "",
  "output": "答案"
}
```

MVP 中 Alpaca Formatter 只接受能够无损表达为单轮 instruction/input/output 的样本。遇到无法无损表达的多轮样本时，返回明确错误，不静默截断。

### 6.2 ShareGPT

典型输出：

```json
{
  "conversations": [
    {"from": "system", "value": "你是一个专业助手"},
    {"from": "human", "value": "问题"},
    {"from": "gpt", "value": "答案"}
  ]
}
```

角色映射由 ShareGPT Formatter 集中管理。

## 7. 技术要求

```text
Python 3.12+
uv
FastAPI
Pydantic
SQLAlchemy 2.0 Async
PostgreSQL
asyncpg
Alembic
pytest
pytest-asyncio
ruff
```

所有项目管理和执行命令统一通过 uv。FastAPI 和 CLI 只是入口，核心处理能力必须能够脱离 Web 单独运行。

## 8. CLI 目标

未来应支持类似命令：

```bash
uv run dataset-builder build input.md --generator qa --format sharegpt --output dataset.jsonl
```

MVP 可以逐步完成 CLI，但架构必须允许 CLI 与 FastAPI 复用同一 Pipeline。

## 9. 非功能要求

- 可追踪：每个样本能追踪到 Chunk 和源文档。
- 可恢复：LLM 调用失败或任务中断后能够从未完成的 Chunk 继续。
- 可扩展：增加 Formatter 时不修改统一 IR 和数据库核心结构。
- 可测试：核心处理器可使用 Fake LLM 和内存对象独立测试。
- 可控：用户能够看到、审核和修改生成结果。
- 轻量：MVP 不引入 Redis、Celery、向量数据库等额外基础设施。

## 10. MVP 验收标准

使用一个 Markdown 文件时，系统能够完成：

1. 导入并解析文档。
2. 将文档切分成多个 Chunk。
3. 调用配置的 OpenAI Compatible API 生成 QA 或 Instruction 样本。
4. 执行清洗、精确去重和结构校验。
5. 在页面或 API 中查看和编辑样本。
6. 审核样本。
7. 将有效且已审核的样本导出为 Alpaca 或 ShareGPT JSONL。
8. 导出过程中不一次性将完整数据集加载到内存。

## 11. 后续方向但不属于 MVP

- 质量评分。
- 自定义 Schema。
- ChatML、OpenAI Messages 等更多格式。
- 近似和语义去重。
- 批量项目处理。
- 可视化 Dataset Pipeline。
- 更完善的任务调度与并发处理。
- 多用户和权限系统。
