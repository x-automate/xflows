import { XFLOWS_CATALOG } from "./catalog-meta";

export const BACKEND_EXECUTION_MAP = Object.fromEntries(
  XFLOWS_CATALOG.filter((component) => component.backendActivity)
    .map((component) => [component.id, component.backendActivity])
);

export function getUnsupportedComponents(nodes) {
  const knownIds = new Set(Object.keys(BACKEND_EXECUTION_MAP));
  return nodes
    .map((node) => node.componentId)
    .filter(
      (componentId) =>
        !knownIds.has(componentId) || !BACKEND_EXECUTION_MAP[componentId]
    );
}
