"""Add base_classes and interfaces columns to classes

Revision ID: 003
Revises: 002
Create Date: 2026-05-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS base_classes JSONB"
    )
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS interfaces JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE classes DROP COLUMN IF EXISTS base_classes")
    op.execute("ALTER TABLE classes DROP COLUMN IF EXISTS interfaces")
