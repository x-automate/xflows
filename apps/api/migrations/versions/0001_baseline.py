from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SCHEMA_PATH.read_text(encoding="utf-8"))


def downgrade() -> None:
    for table in ("idempotency_keys", "run_events", "runs", "triggers", "workflows", "projects", "users"):
        op.get_bind().exec_driver_sql(f"DROP TABLE IF EXISTS {table} CASCADE")
