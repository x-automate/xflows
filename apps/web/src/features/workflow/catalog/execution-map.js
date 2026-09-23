import { XFLOWS_CATALOG } from "./catalog-meta.js";

export const BACKEND_EXECUTION_MAP = Object.fromEntries(
  XFLOWS_CATALOG.filter((component) => component.backendActivity)
    .map((component) => [component.id, component.backendActivity])
);

export function getUnsupportedComponents(nodes) {
  const knownIds = new Set(Object.keys(BACKEND_EXECUTION_MAP));
  return nodes
    .filter((node) => {
      const componentId = node.componentId;
      if (!knownIds.has(componentId) || !BACKEND_EXECUTION_MAP[componentId]) {
        return true;
      }
      const component = XFLOWS_CATALOG.find((item) => item.id === componentId);
      return component?.status === "planned";
    })
    .map((node) => node.componentId);
}
