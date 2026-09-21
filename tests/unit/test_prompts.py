"""Prompt presets and custom text remain compatible with structured output."""

import pytest

from dataset_builder.generators.prompts import list_prompt_presets, resolve_prompt


def test_prompt_presets_and_custom_prompt() -> None:
    presets = list_prompt_presets()
    assert len(presets["qa"]) >= 3
    assert len(presets["instruction"]) >= 3
    assert len(presets["distillation"]) >= 3
    assert "核心问答" not in resolve_prompt("qa", "default")
    assert "pairs" in resolve_prompt("qa", "concise")
    assert "自定义规则" in resolve_prompt("instruction", "custom", " 自定义规则 ")
    assert "items" in resolve_prompt("instruction", "custom", "自定义规则")
    multi_turn = resolve_prompt("qa", "default", multi_turn=True)
    assert "messages" in multi_turn
    assert "至少包含两轮" in multi_turn
    assert '"answer"' in resolve_prompt("distillation", "faithful")
    assert all(item["multi_turn"] is False for items in presets.values() for item in items)


@pytest.mark.parametrize("mode,preset,custom", [
    ("unknown", "default", None), ("qa", "missing", None), ("qa", "custom", " "),
])
def test_invalid_prompt_selection(mode: str, preset: str, custom: str | None) -> None:
    with pytest.raises(ValueError):
        resolve_prompt(mode, preset, custom)
