from uuid import uuid4

from dataset_builder.application.preferences import PreferenceService, PreferenceValidator, preference_hash
from dataset_builder.formatters import ShareGPTPreferenceFormatter
from dataset_builder.models import Message, MessageRole, PreferencePair


def test_preference_validator_accepts_shared_conversation_context() -> None:
    context = [
        {"role": "system", "content": "专业助手"},
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
    ]
    chosen = {"role": "assistant", "content": "更好的回答"}
    rejected = {"role": "assistant", "content": "较差的回答"}

    assert PreferenceValidator().validate(context, chosen, rejected) == []
    assert preference_hash(context, chosen, rejected) == preference_hash(context, chosen, rejected)


def test_preference_validator_rejects_different_or_identical_responses() -> None:
    issues = PreferenceValidator().validate(
        [{"role": "assistant", "content": "错误上下文"}],
        {"role": "assistant", "content": "相同"},
        {"role": "assistant", "content": "相同"},
    )

    assert {rule for rule, _ in issues} == {"context_not_user", "invalid_order", "identical_responses"}


def test_shared_pair_requires_identical_context() -> None:
    chosen = [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "好"}]
    rejected = [{"role": "user", "content": "另一个问题"}, {"role": "assistant", "content": "差"}]

    try:
        PreferenceService._extract_shared_pair(chosen, rejected)
    except ValueError as exc:
        assert "共同上下文不一致" in str(exc)
    else:
        raise AssertionError("不同上下文应被拒绝")


def test_sharegpt_preference_formatter_maps_pair() -> None:
    pair = PreferencePair(
        project_id=uuid4(),
        context_messages=[Message(role=MessageRole.USER, content="问题")],
        chosen_response=Message(role=MessageRole.ASSISTANT, content="好回答"),
        rejected_response=Message(role=MessageRole.ASSISTANT, content="差回答"),
    )

    assert ShareGPTPreferenceFormatter().format(pair) == {
        "conversations": [{"from": "human", "value": "问题"}],
        "chosen": {"from": "gpt", "value": "好回答"},
        "rejected": {"from": "gpt", "value": "差回答"},
    }
