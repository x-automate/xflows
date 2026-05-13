from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkflowNode(BaseModel):
    id: str
    componentId: str
    x: float | None = None
    y: float | None = None
    parent: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: str | None = None
    slot: str | None = None


class WorkflowCreateRequest(BaseModel):
    id: str
    name: str
    description: str | None = None
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRecord(BaseModel):
    id: str
    name: str
    description: str | None = None
    version: int
    status: Literal["draft", "published", "archived"]
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime
    updatedAt: datetime


class RunRequest(BaseModel):
    input: str
    idempotencyKey: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    id: str
    projectId: str | None = None
    workflowId: str
    workflowVersion: int
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    input: str
    output: str | None = None
    error: str | None = None
    traceId: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    startedAt: datetime | None = None
    finishedAt: datetime | None = None


class RunEvent(BaseModel):
    id: int | None = None
    runId: str
    type: Literal[
        "run_started",
        "node_started",
        "node_succeeded",
        "node_failed",
        "run_succeeded",
        "run_failed",
    ]
    timestamp: datetime
    nodeId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    traceId: str | None = None


class ProjectCreateRequest(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None


class ProjectRecord(BaseModel):
    id: str
    ownerUserId: str | None = None
    name: str
    description: str | None = None
    graph: dict[str, Any] | None = None
    configs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    lastRun: dict[str, Any] | None = None
    createdAt: datetime
    updatedAt: datetime


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    graph: dict[str, Any] | None = None
    configs: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    lastRun: dict[str, Any] | None = None


class TriggerRecord(BaseModel):
    id: str
    projectId: str
    type: Literal["time", "webhook", "event"]
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime
    updatedAt: datetime


class TriggerCreateRequest(BaseModel):
    type: Literal["time", "webhook", "event"]
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class TriggerUpdateRequest(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class ProjectWorkflowPayload(BaseModel):
    name: str
    description: str | None = None
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectRunRequest(BaseModel):
    input: str
    idempotencyKey: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    workflow: ProjectWorkflowPayload


class InternalRunEventRequest(BaseModel):
    type: Literal[
        "run_started",
        "node_started",
        "node_succeeded",
        "node_failed",
        "run_succeeded",
        "run_failed",
    ]
    nodeId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    traceId: str | None = None


class UserCreateRequest(BaseModel):
    email: str
    name: str
    authProvider: str = "local"


class UserRecord(BaseModel):
    id: str
    email: str
    name: str
    authProvider: str
    createdAt: datetime
    updatedAt: datetime
