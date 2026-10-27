import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finql.agent.models import Message, MessageRole


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None  # the start of the first question; None until the first message
    created_at: datetime
    updated_at: datetime


class MessageRequest(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=2000,
        examples=["Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat szerint?"],
    )


class MessageOut(BaseModel):
    """A stored step of the conversation. The model's thinking blocks are left out: they are
    opaque (signed) and only the model reads them."""

    id: int
    role: MessageRole
    content: dict[str, Any]
    model: str | None
    input_tokens: int
    output_tokens: int
    created_at: datetime

    @classmethod
    def from_message(cls, message: Message) -> "MessageOut":
        content = dict(message.content)
        if "blocks" in content:
            content["blocks"] = [
                block for block in content["blocks"] if block.get("type") in ("text", "tool_use")
            ]
        return cls(
            id=message.id,
            role=message.role,
            content=content,
            model=message.model,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            created_at=message.created_at,
        )


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
