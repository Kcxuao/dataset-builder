"""Structured multi-turn LLM response helpers."""

from pydantic import BaseModel, Field, model_validator

from dataset_builder.models import Message, MessageRole


class ConversationItem(BaseModel):
    """One complete training conversation, kept together as one sample."""

    messages: list[Message] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_message_order(self) -> "ConversationItem":
        expected = MessageRole.USER
        for index, message in enumerate(self.messages):
            if index == 0 and message.role is MessageRole.SYSTEM:
                continue
            if message.role is not expected:
                raise ValueError(f"message {index} must have role {expected}")
            expected = MessageRole.ASSISTANT if expected is MessageRole.USER else MessageRole.USER
        if expected is not MessageRole.USER:
            raise ValueError("conversation must end with an assistant message")
        if not all(message.content.strip() for message in self.messages):
            raise ValueError("conversation messages must not be blank")
        return self


class ConversationResponse(BaseModel):
    items: list[ConversationItem] = Field(min_length=1)


def validate_turn_mode(messages: list[Message], multi_turn: bool) -> None:
    turns = sum(message.role is MessageRole.ASSISTANT for message in messages)
    if multi_turn and turns < 2:
        raise ValueError("多轮模式要求每条样本至少包含两轮问答")
    if not multi_turn and turns != 1:
        raise ValueError("单轮模式要求每条样本恰好包含一轮问答")
