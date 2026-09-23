from __future__ import annotations

import asyncio

from prometheus_client import start_http_server
from temporalio.client import Client
from temporalio.worker import Worker

from .activities import (
    complete_run,
    execute_node,
    load_workflow,
    prepare_approval,
    record_approval,
    record_node_statuses,
)
from .config import settings
from .workflows import (
    ApiGenDeployWorkflow,
    ApiGenGenerateWorkflow,
    ApiGenValidateWorkflow,
    XFlowsWorkflow,
)


async def run_worker() -> None:
    start_http_server(9464)
    client = await Client.connect(
        settings.temporal_host_port,
        namespace=settings.temporal_namespace,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[XFlowsWorkflow, ApiGenGenerateWorkflow, ApiGenValidateWorkflow, ApiGenDeployWorkflow],
        activities=[
            execute_node,
            complete_run,
            record_node_statuses,
            load_workflow,
            prepare_approval,
            record_approval,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
