"""Add pgvector extension and embedding column to functions

Revision ID: 002
Revises: 001
Create Date: 2026-05-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add embedding column to functions table
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS embedding vector(1536)"
    )


def downgrade() -> None:
    # Remove embedding column
    op.execute("ALTER TABLE functions DROP COLUMN IF EXISTS embedding")
    # Note: we keep the vector extension installed (no harm, and removing it
    # would cascade-drop the column anyway since it uses a custom type)
