import nodeRegistry from "./node-registry.json";

export const XFLOWS_ICONS = {
  input: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12h12"/><path d="M12 8l4 4-4 4"/><circle cx="20" cy="12" r="1.5" fill="currentColor"/></svg>',
  output: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="4" cy="12" r="1.5" fill="currentColor"/><path d="M8 12h12"/><path d="M16 8l4 4-4 4"/></svg>',
  prompt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v12H8l-4 4z"/><path d="M8 9h8M8 12h5"/></svg>',
  openai: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2a4 4 0 0 0-3.46 6 4 4 0 0 0 0 8 4 4 0 0 0 6.92 0 4 4 0 0 0 0-8A4 4 0 0 0 12 2z"/><path d="M12 8v8M8 10l8 4M16 10l-8 4" stroke-width="1.2"/></svg>',
  anthropic: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4l-4 16h3l1-4h6l1 4h3L13 4H7zm0 8l2-6 2 6H7zm10-8l4 16h-3l-4-16h3z"/></svg>',
  http: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
  code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 6l-4 12"/></svg>',
  vector: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
  sum: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 4h14L11 12l8 8H5l8-8L5 4z"/></svg>',
  branch: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="12" r="2"/><path d="M8 6c0 4 8 4 8 6M8 18c0-4 8-4 8-6"/></svg>',
  json: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 4c-2 0-3 1-3 3v3c0 1-1 2-2 2 1 0 2 1 2 2v3c0 2 1 3 3 3M16 4c2 0 3 1 3 3v3c0 1 1 2 2 2-1 0-2 1-2 2v3c0 2-1 3-3 3"/></svg>',
  regex: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 4v8M8.5 6l7 4M8.5 10l7-4"/><circle cx="6" cy="18" r="2" fill="currentColor"/></svg>',
  agent: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="8" width="12" height="10" rx="2"/><path d="M12 4v4M9 12v2M15 12v2"/><circle cx="3" cy="13" r="1.5"/><circle cx="21" cy="13" r="1.5"/></svg>',
  markdown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 14V10l2 3 2-3v4M15 10v4M13 12l2 2 2-2"/></svg>',
  trace: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><path d="M12 4v2M12 18v2M4 12h2M18 12h2"/></svg>',
  guard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></svg>',
  litellm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L4 14h6l-1 8 9-12h-6z"/></svg>',
  hook: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 8v7a4 4 0 1 0 8 0V7a3 3 0 0 0-6 0v8a2 2 0 1 0 4 0V9"/></svg>',
};

export const XFLOWS_CATALOG = nodeRegistry.components;
export const CATEGORY_COLORS = nodeRegistry.categoryColors;

const CATALOG_BY_ID = Object.fromEntries(
  XFLOWS_CATALOG.map((component) => [component.id, component])
);

export function getComponentMeta(componentId) {
  return CATALOG_BY_ID[componentId] || null;
}

export function getRequiredProjectConfigs(nodes = []) {
  const seen = new Set();
  const requirements = [];
  for (const node of nodes) {
    const meta = getComponentMeta(node.componentId);
    const projectConfigs = meta?.projectConfigs || [];
    for (const config of projectConfigs) {
      if (!config?.key || seen.has(config.key)) continue;
      seen.add(config.key);
      requirements.push({
        ...config,
        componentId: meta.id,
        componentName: meta.name,
      });
    }
  }
  return requirements;
}
