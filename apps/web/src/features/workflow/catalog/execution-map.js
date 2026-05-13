import { XFLOWS_CATALOG } from "./catalog-meta";

export const BACKEND_EXECUTION_MAP = {
  Input: "xflows.execute_node",
  Output: "xflows.execute_node",
  PromptTemplate: "xflows.execute_node",
  LLM: "xflows.execute_node",
  OpenAIChat: "xflows.execute_node",
  AnthropicChat: "xflows.execute_node",
  HttpRequest: "xflows.execute_node",
  WebSearch: "xflows.execute_node",
  CodeExec: "xflows.execute_node",
  VectorStore: "xflows.execute_node",
  Summarizer: "xflows.execute_node",
  IfElse: "xflows.execute_node",
  JsonParser: "xflows.execute_node",
  RegexExtract: "xflows.execute_node",
  ReActAgent: "xflows.execute_node",
  Markdown: "xflows.execute_node",
  Tracer: "xflows.execute_node",
  Guardrail: "xflows.execute_node",
};

export function getUnsupportedComponents(nodes) {
  const knownIds = new Set(XFLOWS_CATALOG.map((component) => component.id));
  return nodes
    .map((node) => node.componentId)
    .filter(
      (componentId) =>
        !knownIds.has(componentId) || !BACKEND_EXECUTION_MAP[componentId]
    );
}
