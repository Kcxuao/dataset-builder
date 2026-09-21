"""Built-in task prompts and per-run custom prompt resolution."""

QA_FORMAT = '只返回一个 json 对象，不要解释或代码块，格式为 {"pairs": [{"question": "...", "answer": "..."}]}。'
INSTRUCTION_FORMAT = (
    '只返回一个 json 对象，不要解释或代码块，格式为 '
    '{"items": [{"instruction": "...", "response": "..."}]}。'
)
AUGMENTATION_FORMAT = (
    '只返回一个 json 对象，不要解释或代码块，格式为 '
    '{"items": [{"messages": [{"role": "user", "content": "..."}, '
    '{"role": "assistant", "content": "..."}]}]}。'
)

PROMPT_PRESETS = {
    "qa": [
        {"id": "default", "name": "标准问答", "instruction": "根据文本生成可直接回答的问题与答案。"},
        {"id": "concise", "name": "核心问答", "instruction": "只生成一个最重要、答案可从文本直接找到的问答。"},
        {"id": "diverse", "name": "多角度问答", "instruction": "从不同角度生成两到三个问答，不要编造信息。"},
    ],
    "instruction": [
        {"id": "default", "name": "标准指令", "instruction": "根据提供的文本生成一个或多个可由文本支持的指令与回答。"},
        {"id": "concise", "name": "简洁指令", "instruction": "根据文本生成一条明确、简短的任务指令和对应回答。"},
        {"id": "detailed", "name": "详细指令", "instruction": "生成两到三条不同任务的指令与完整回答，严格依据原文。"},
    ],
    "augmentation": [
        {
            "id": "balanced",
            "name": "平衡扩增",
            "instruction": "严格依据种子样本与来源内容，生成有明显差异的新训练样本。",
        },
        {
            "id": "precise",
            "name": "事实优先",
            "instruction": "只表达来源中可验证的信息；信息不足时不要补充或猜测。",
        },
    ],
}


def list_prompt_presets() -> dict[str, list[dict[str, str]]]:
    return {
        mode: [{"id": item["id"], "name": item["name"], "prompt": item["instruction"]} for item in items]
        for mode, items in PROMPT_PRESETS.items()
    }


def resolve_prompt(mode: str, preset: str = "default", custom_prompt: str | None = None) -> str:
    if mode not in PROMPT_PRESETS:
        raise ValueError("生成方式无效")
    if preset == "custom":
        instruction = (custom_prompt or "").strip()
        if not instruction:
            raise ValueError("自定义提示词不能为空")
    else:
        selected = next((item for item in PROMPT_PRESETS[mode] if item["id"] == preset), None)
        if selected is None:
            raise ValueError("提示词预设不存在")
        instruction = selected["instruction"]
    output_format = QA_FORMAT if mode == "qa" else INSTRUCTION_FORMAT if mode == "instruction" else AUGMENTATION_FORMAT
    return instruction + "\n" + output_format
