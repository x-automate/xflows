from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, timezone

from app.models import RunEvent, WorkflowCreateRequest


def _event(run_id: str, event_key: str | None) -> RunEvent:
    return RunEvent(
        runId=run_id,
        type="node_succeeded",
        nodeId="n1",
        payload={"output": "x"},
        timestamp=datetime.now(timezone.utc),
        traceId="trace_1",
        eventKey=event_key,
    )


TEST_DATABASE_URL = os.environ.get("XFLOW_TEST_DATABASE_URL")


class InMemoryStoreEventDedupeTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_event_key_is_deduped(self) -> None:
        from app.store import InMemoryStore

        store = InMemoryStore()
        first = await store.append_event(_event("run_1", "run_1:n1:node_succeeded:1"))
        duplicate = await store.append_event(_event("run_1", "run_1:n1:node_succeeded:1"))
        await store.append_event(_event("run_1", "run_1:n1:node_succeeded:2"))

        self.assertEqual(first.id, duplicate.id)
        self.assertEqual(first.eventKey, duplicate.eventKey)
        events = await store.get_events("run_1")
        self.assertEqual(
            [event.eventKey for event in events],
            ["run_1:n1:node_succeeded:1", "run_1:n1:node_succeeded:2"],
        )

    async def test_events_without_key_are_never_deduped(self) -> None:
        from app.store import InMemoryStore

        store = InMemoryStore()
        await store.append_event(_event("run_1", None))
        await store.append_event(_event("run_1", None))
        events = await store.get_events("run_1")
        self.assertEqual(len(events), 2)


class PostgresStoreEventDedupeTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_event_key_is_deduped(self) -> None:
        database_url = TEST_DATABASE_URL or os.environ.get("XFLOW_TEST_DATABASE_URL")
        if not database_url:
            self.skipTest("XFLOW_TEST_DATABASE_URL not set")
        import asyncpg

        from app.store import PostgresStore

        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
        store = PostgresStore(pool, None)
        try:
            workflow = await store.create_workflow(
                WorkflowCreateRequest(
                    id=f"wf_{uuid.uuid4().hex[:8]}",
                    name="event-dedupe-test",
                    nodes=[],
                    edges=[],
                )
            )
            run = await store.create_run(workflow.id, 1, "x", "trace_1")
            first = await store.append_event(_event(run.id, f"{run.id}:n1:node_succeeded:1"))
            duplicate = await store.append_event(_event(run.id, f"{run.id}:n1:node_succeeded:1"))
            events = await store.get_events(run.id)
            self.assertEqual(first.id, duplicate.id)
            self.assertEqual(len(events), 1)
        finally:
            await pool.close()


if __name__ == "__main__":
    unittest.main()
