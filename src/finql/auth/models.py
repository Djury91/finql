import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from finql.core.base_model import Base


class UserRole(enum.StrEnum):
    BRANCH_MANAGER = "branch_manager"  # one branch's customers, accounts, transactions
    ANALYST = "analyst"  # every branch, no PII
    AUDITOR = "auditor"  # the query log and conversations, no bank data
    ADMIN = "admin"  # users, documents, few-shot examples


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # A branch manager sees one branch; everyone else is not tied to a branch.
        CheckConstraint(
            "(role = 'branch_manager') = (branch_id IS NOT NULL)", name="branch_matches_role"
        ),
        # Stored normalized, so the unique constraint is case-insensitive in effect.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("bank.branches.branch_id"))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    # LLM tokens per day (phase 3, llm/usage.py).
    daily_token_budget: Mapped[int] = mapped_column(server_default=text("200000"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
