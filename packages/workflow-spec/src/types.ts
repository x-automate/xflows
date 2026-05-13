export type WorkflowStatus = "draft" | "published" | "archived";

export interface WorkflowNode {
  id: string;
  componentId: string;
  x: number;
  y: number;
  params: Record<string, unknown>;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description?: string;
  version: number;
  status: WorkflowStatus;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  metadata?: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface RunRequest {
  input: string;
  idempotencyKey?: string;
  metadata?: Record<string, unknown>;
}

export interface RunRecord {
  id: string;
  workflowId: string;
  workflowVersion: number;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  input: string;
  output?: string;
  error?: string;
  startedAt?: string;
  finishedAt?: string;
  traceId?: string;
}

export interface RunEvent {
  runId: string;
  type:
    | "run_started"
    | "node_started"
    | "node_succeeded"
    | "node_failed"
    | "run_succeeded"
    | "run_failed";
  nodeId?: string;
  payload?: Record<string, unknown>;
  timestamp: string;
  traceId?: string;
}
