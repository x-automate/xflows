"""Trigger execution (docs 06 XU-8): webhook receiver + time-trigger scheduler.

Webhook triggers fire via ``POST /webhooks/{trigger_id}`` with an HMAC
signature (registration secret generated at trigger creation) and exactly-once
run creation through the existing idempotency path.

Time triggers fire via a lightweight scheduler tick: for every enabled time
trigger, each interval slot maps to one idempotency key, so a slot fires a run
exactly once even under duplicate ticks.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 60  # minimum fire cadence
MAX_CATCHUP_S = 3600


def _trigger_interval_seconds(config: dict) -> int:
    for key in ("intervalSeconds", "everySeconds"):
        try:
            return max(DEFAULT_INTERVAL_S, int(config[key]))
        except (KeyError, TypeError, ValueError):
            continue
    try:
        return max(DEFAULT_INTERVAL_S, int(float(config.get("everyMinutes", 0)) * 60))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_S


def trigger_slot_key(trigger_id: str, config: dict, now: datetime) -> str:
    interval = _trigger_interval_seconds(config)
    epoch = now.timestamp()
    slot = int(epoch // interval) * interval
    return f"trigger:{trigger_id}:{slot}"


def webhook_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def fire_due_triggers(store, *, now: datetime | None = None, create_run) -> list[str]:
    """Fire every due, enabled time trigger exactly once per slot.

    ``create_run(workflow_id, idempotency_key, input) -> RunRecord | None``
    encapsulates run creation. A slot whose idempotency key already exists is
    skipped, so duplicate ticks never fire a second run.
    """
    now = now or datetime.now(tz=timezone.utc)
    fired: list[str] = []
    for trigger in await store.list_enabled_triggers("time"):
        config = trigger.config or {}
        workflow_id = str(config.get("workflowId", ""))
        if not workflow_id:
            continue
        key = trigger_slot_key(trigger.id, config, now)
        if await store.find_run_by_idempotency_key(workflow_id, key) is not None:
            continue
        run = await create_run(workflow_id, key, str(config.get("input", "")))
        if run is not None:
            fired.append(run.id)
    return fired


async def trigger_scheduler_loop(store, create_run, *, interval_s: float = 30.0) -> None:
    """Background tick loop; each tick fires due time triggers once."""
    while True:  # pragma: no cover - lifecycle loop
        try:
            await fire_due_triggers(store, create_run=create_run)
        except Exception as error:  # noqa: BLE001 — the scheduler must survive
            logger.warning("Trigger scheduler tick failed: %s", error)
        await asyncio.sleep(max(1.0, interval_s))
