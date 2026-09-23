from __future__ import annotations

from alembic import op

revision = "0002_event_keys"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE run_events ADD COLUMN IF NOT EXISTS event_key TEXT NULL")
    op.get_bind().exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_run_events_run_event_key "
        "ON run_events (run_id, event_key) WHERE event_key IS NOT NULL"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP INDEX IF EXISTS uq_run_events_run_event_key")
    op.get_bind().exec_driver_sql("ALTER TABLE run_events DROP COLUMN IF EXISTS event_key")
