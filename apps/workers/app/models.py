from typing import Any

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


class WorkflowDefinition(BaseModel):
    id: str
    name: str
    version: int
    status: str
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
