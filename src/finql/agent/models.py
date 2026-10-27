import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finql.core.base_model import Base


class MessageRole(enum.StrEnum):
    USER = "user"  # the question
    ASSISTANT = "assistant"  # one model turn: text, tool calls; or a turn that failed
    TOOL = "tool"  # one tool call with its input and result
    SUMMARY = "summary"  # the earlier part of a long conversation, summarized (memory)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(None, "user_id", "updated_at"),
        {"comment": "Beszélgetések az agenttel: egy felhasználóé, az üzenetek a messages-ben."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"))
    title: Mapped[str | None] = mapped_column(Text)  # the start of the first question
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """Every step of a conversation: the question, each model turn, each tool call, the
    summaries. Append-only like the logs (db/app/030_messages.sql): a conversation is evidence
    of what the agent did, and it counts in the daily token budget."""

    __tablename__ = "messages"
    __table_args__ = (
        # A conversation in order.
        Index(None, "conversation_id", "id"),
        # The daily token budget: one user's rows.
        Index(None, "user_id", "created_at"),
        {"comment": "Az agent-beszélgetések lépései, eszközhívásokkal. Csak hozzáfűzhető."},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.conversations.id"))
    # The conversation's owner, repeated: the budget query needs no join.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"))
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            name="message_role",
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    # By role (agent/memory.py reads it back):
    #   user:      {"text": ...}
    #   assistant: {"blocks": [...], "stop_reason": ...}, the final one also
    #              {"answer": ..., "citations": [...]}; a failed turn {"error": ..., "message": ...}
    #   tool:      {"tool_use_id", "name", "input", "is_error", "result", "details", "duration_ms"}
    #   summary:   {"text": ..., "through_message_id": ...}
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    llm_latency_ms: Mapped[int | None]
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
