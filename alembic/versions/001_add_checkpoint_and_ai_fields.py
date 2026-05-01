"""Add checkpoint and AI/Expert fields

This migration adds all columns that were previously added via bare ALTER TABLE
in main.py's startup_event. All operations use IF NOT EXISTS for idempotency.

Revision ID: 001
Revises:
Create Date: 2026-05-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === AnalysisTask checkpoint/resume fields ===
    op.execute(
        "ALTER TABLE analysis_tasks "
        "ADD COLUMN IF NOT EXISTS processed_files JSONB DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE analysis_tasks "
        "ADD COLUMN IF NOT EXISTS last_processed_file VARCHAR(500)"
    )
    op.execute(
        "ALTER TABLE analysis_tasks "
        "ADD COLUMN IF NOT EXISTS total_files INTEGER DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE analysis_tasks "
        "ADD COLUMN IF NOT EXISTS checkpoint_data JSONB"
    )

    # === Project analysis_mode ===
    op.execute(
        "ALTER TABLE projects "
        "ADD COLUMN IF NOT EXISTS analysis_mode VARCHAR(20) DEFAULT 'ai'"
    )

    # === Function AI-oriented fields ===
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS ai_purpose TEXT"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS ai_inputs JSONB"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS ai_outputs JSONB"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS ai_side_effects JSONB"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS return_type VARCHAR(255)"
    )

    # === Function Expert mode fields ===
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS expert_purpose TEXT"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS expert_tech_details TEXT"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS expert_error_handling TEXT"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS expert_concurrency TEXT"
    )
    op.execute(
        "ALTER TABLE functions "
        "ADD COLUMN IF NOT EXISTS expert_tradeoffs TEXT"
    )

    # === Class AI-oriented fields ===
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS ai_purpose TEXT"
    )
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS ai_interfaces JSONB"
    )

    # === Class Expert mode fields ===
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS expert_purpose TEXT"
    )
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS expert_architecture TEXT"
    )
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS expert_responsibilities TEXT"
    )
    op.execute(
        "ALTER TABLE classes "
        "ADD COLUMN IF NOT EXISTS expert_extension_points TEXT"
    )


def downgrade() -> None:
    """Downgrade removes all the added columns."""
    # AnalysisTask
    op.drop_column("analysis_tasks", "processed_files")
    op.drop_column("analysis_tasks", "last_processed_file")
    op.drop_column("analysis_tasks", "total_files")
    op.drop_column("analysis_tasks", "checkpoint_data")

    # Project
    op.drop_column("projects", "analysis_mode")

    # Function AI
    op.drop_column("functions", "ai_purpose")
    op.drop_column("functions", "ai_inputs")
    op.drop_column("functions", "ai_outputs")
    op.drop_column("functions", "ai_side_effects")
    op.drop_column("functions", "return_type")

    # Function Expert
    op.drop_column("functions", "expert_purpose")
    op.drop_column("functions", "expert_tech_details")
    op.drop_column("functions", "expert_error_handling")
    op.drop_column("functions", "expert_concurrency")
    op.drop_column("functions", "expert_tradeoffs")

    # Class AI
    op.drop_column("classes", "ai_purpose")
    op.drop_column("classes", "ai_interfaces")

    # Class Expert
    op.drop_column("classes", "expert_purpose")
    op.drop_column("classes", "expert_architecture")
    op.drop_column("classes", "expert_responsibilities")
    op.drop_column("classes", "expert_extension_points")
