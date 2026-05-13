from __future__ import annotations

import asyncio

from prometheus_client import start_http_server
from temporalio.client import Client
from temporalio.worker import Worker

from .activities import complete_run, execute_node
from .config import settings
from .workflows import XFlowsWorkflow


async def run_worker() -> None:
    start_http_server(9464)
    client = await Client.connect(
        settings.temporal_host_port,
        namespace=settings.temporal_namespace,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[XFlowsWorkflow],
        activities=[execute_node, complete_run],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
