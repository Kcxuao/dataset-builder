import pytest

from dataset_builder.application.augmentation import (
    STRATEGIES,
    AugmentationItem,
    AugmentationResponse,
    AugmentationService,
)
from dataset_builder.generators.conversation import validate_turn_mode
from dataset_builder.generators.prompts import list_prompt_presets, resolve_prompt
from dataset_builder.models import Message, MessageRole


def test_augmentation_prompt_has_structured_output_contract() -> None:
    prompt = resolve_prompt("augmentation", "balanced")

    assert "items" in prompt
    assert "messages" in prompt
    assert "balanced" in {item["id"] for item in list_prompt_presets()["augmentation"]}


def test_augmentation_validates_strategies_and_target() -> None:
    assert AugmentationService.validate_options(["rewrite", "rewrite", "scenario"], 2) == ("rewrite", "scenario")
    with pytest.raises(ValueError, match="扩增策略"):
        AugmentationService.validate_options(["unknown"], 2)
    with pytest.raises(ValueError, match="目标新增数量"):
        AugmentationService.validate_options(["rewrite"], 0)


def test_augmentation_response_requires_messages() -> None:
    response = AugmentationResponse.model_validate(
        {"items": [{"messages": [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"}]}]}
    )

    assert response.items[0].messages[0].role == MessageRole.USER
    assert len(STRATEGIES) == 5
    with pytest.raises(ValueError):
        AugmentationItem(messages=[Message(role=MessageRole.USER, content="只有一条")])


def test_augmentation_multi_turn_response_keeps_all_turns_in_one_item() -> None:
    item = AugmentationItem.model_validate({"messages": [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "追问"},
        {"role": "assistant", "content": "第二答"},
    ]})

    validate_turn_mode(item.messages, True)
    assert len(item.messages) == 4
