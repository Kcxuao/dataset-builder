# Codex 启动提示词

## 第一次进入项目

将下面内容发送给 Codex：

```text
请先阅读项目根目录的 AGENTS.md，以及 docs/PROJECT_SPEC.md、docs/ARCHITECTURE.md 和 docs/PROGRESS.md。然后检查当前仓库结构，用中文概括项目目标、MVP 边界、核心架构、统一 IR、技术约束和当前开发进度。在我确认之前先不要编写代码，也不要扩展需求。
```

## 确认理解后开始开发

```text
按照 AGENTS.md 的要求，开始完成 docs/PROGRESS.md 中第一个未完成任务。先检查现有代码并简要说明本次修改范围，然后直接实现。完成后运行相关测试和 ruff，更新 docs/PROGRESS.md，并汇报修改文件、验证结果和剩余问题。不要实现 MVP 之外的功能。
```

## 继续上次进度

```text
请重新阅读 AGENTS.md、docs/PROJECT_SPEC.md、docs/ARCHITECTURE.md 和 docs/PROGRESS.md，检查代码是否与进度记录一致，然后继续完成下一个未完成任务。不要重复已经完成的工作。
```

## 验证 Codex 是否读取指令

在项目根目录运行：

```bash
codex --ask-for-approval never "请总结当前项目加载到的指令、MVP 边界和下一步任务"
```

如果刚刚修改了 `AGENTS.md`，退出并重新启动 Codex，使新会话重新加载项目指令。
