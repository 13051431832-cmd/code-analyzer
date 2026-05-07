"""Add ai_patterns JSONB column to classes

Revision ID: 004
Revises: 003
Create Date: 2026-05-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS ai_patterns JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE classes DROP COLUMN IF EXISTS ai_patterns")
