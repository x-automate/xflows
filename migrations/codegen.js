// Validation + execution engine for XFlows
// Edges have a `kind`: 'data' (left/right) or 'config' (bottom → another node's config port)
function topoSort(nodes, edges) {
  const dataEdges = edges.filter(e => (e.kind || 'data') === 'data');
  const incoming = Object.fromEntries(nodes.map(n => [n.id, 0]));
  const adj = Object.fromEntries(nodes.map(n => [n.id, []]));
  for (const e of dataEdges) {
    incoming[e.target] = (incoming[e.target] || 0) + 1;
    adj[e.source].push(e.target);
  }
  // Config-only nodes (aux: Observability/Memory not on main flow) start as roots too
  const q = nodes.filter(n => incoming[n.id] === 0).map(n => n.id);
  const order = [];
  while (q.length) {
    const id = q.shift();
    order.push(id);
    for (const nx of adj[id]) {
      incoming[nx]--;
      if (incoming[nx] === 0) q.push(nx);
    }
  }
  return order.length === nodes.length ? order : null;
}

function meta(n) {
  return window.XFLOWS_CATALOG.find(c => c.id === n.componentId) || { name: '?', kind: 'transform', params: [], category: '?' };
}

function validate(nodes, edges) {
  const errors = [];
  if (nodes.length === 0) {
    errors.push('Canvas is empty — drop a node to get started.');
    return { errors, order: [] };
  }
  const order = topoSort(nodes, edges);
  if (!order) {
    errors.push('Workflow contains a cycle. Remove the looping connection.');
    return { errors, order: [] };
  }
  const dataEdges = edges.filter(e => (e.kind || 'data') === 'data');
  const configEdges = edges.filter(e => e.kind === 'config');

  const outDeg = Object.fromEntries(nodes.map(n => [n.id, 0]));
  const inDeg  = Object.fromEntries(nodes.map(n => [n.id, 0]));
  dataEdges.forEach(e => { outDeg[e.source]++; inDeg[e.target]++; });

  const inputs  = nodes.filter(n => meta(n).kind === 'input');
  const outputs = nodes.filter(n => meta(n).kind === 'output');
  if (inputs.length === 0) errors.push('Workflow needs an Input node (entry point).');
  if (inputs.length > 1)   errors.push('Multiple Input nodes — only one allowed.');
  if (outputs.length === 0) errors.push('Workflow needs an Output node (final step).');
  if (outputs.length > 1)   errors.push('Multiple Output nodes — only one allowed.');

  // Aux nodes (Observability, etc.) must be connected via a config edge
  nodes.forEach(n => {
    const m = meta(n);
    const isAux = m.category === 'Observability' || (m.kind === 'aux' && m.category !== 'Memory');
    const auxLike = m.category === 'Observability';
    if (auxLike) {
      const usedAsConfig = configEdges.some(e => e.source === n.id);
      if (!usedAsConfig) errors.push(`"${m.name}" must be connected to a node's config port (drag from its bottom).`);
    } else if (m.id === 'VectorStore' || m.category === 'Tool' || m.category === 'Memory') {
      // May be on the data flow OR attached via a config edge (tools/memory slot)
      const onData = outDeg[n.id] > 0 || inDeg[n.id] > 0;
      const onConfig = configEdges.some(e => e.source === n.id);
      if (!onData && !onConfig) errors.push(`"${m.name}" is not connected.`);
    } else if (m.kind === 'provider') {
      if (!n.parent) errors.push(`"${m.name}" must be placed inside an ${m.requiresContainer} container.`);
    } else if (m.kind === 'container') {
      const child = nodes.find(c => c.parent === n.id);
      if (!child) errors.push(`"${m.name}" container is empty — drop a provider inside it.`);
      if (nodes.length > 1 && outDeg[n.id] === 0 && inDeg[n.id] === 0) errors.push(`"${m.name}" is not connected.`);
    } else {
      if (nodes.length > 1 && outDeg[n.id] === 0 && inDeg[n.id] === 0) {
        errors.push(`"${m.name}" is not connected.`);
      }
    }
  });

  outputs.forEach(o => { if (outDeg[o.id] > 0) errors.push(`Output "${meta(o).name}" must be terminal.`); });
  inputs.forEach(i => { if (inDeg[i.id] > 0) errors.push(`Input "${meta(i).name}" cannot have incoming edges.`); });

  // Validate config edges target a valid slot
  configEdges.forEach(e => {
    const target = nodes.find(n => n.id === e.target);
    if (!target) return;
    const m = meta(target);
    const slot = (m.configs || []).find(s => s.name === e.slot);
    if (!slot) {
      errors.push(`"${m.name}" does not accept config "${e.slot}".`);
      return;
    }
    const src = nodes.find(n => n.id === e.source);
    if (!src) return;
    const srcCat = meta(src).category;
    if (slot.accepts && !slot.accepts.includes(srcCat)) {
      errors.push(`"${meta(src).name}" (${srcCat}) cannot connect to "${m.name}.${e.slot}" (expects ${slot.accepts.join(', ')}).`);
    }
  });

  return { errors, order };
}

async function execute(nodes, edges, userInput, ctx, onEvent) {
  // Skip nested provider nodes from main execution graph — their parent container runs them.
  const containers = nodes.filter(n => meta(n).kind === 'container');
  const childOf = {};
  containers.forEach(c => {
    const child = nodes.find(n => n.parent === c.id);
    if (child) childOf[c.id] = child;
  });
  const nestedIds = new Set(Object.values(childOf).map(c => c.id));
  const topNodes = nodes.filter(n => !nestedIds.has(n.id));
  const topEdges = edges.filter(e => !nestedIds.has(e.source) && !nestedIds.has(e.target));

  const { errors, order } = validate(nodes, edges);
  if (errors.length) throw new Error(errors[0]);

  const dataEdges = topEdges.filter(e => (e.kind || 'data') === 'data');
  const configEdges = topEdges.filter(e => e.kind === 'config');
  const adj = Object.fromEntries(topNodes.map(n => [n.id, []]));
  dataEdges.forEach(e => adj[e.source].push(e.target));

  const values = {};
  const inputNode = nodes.find(n => meta(n).kind === 'input');
  if (inputNode) values[inputNode.id] = { value: userInput };

  // Pre-run aux/config-source nodes so consumers have their values ready
  const configSourceIds = new Set(configEdges.map(e => e.source));
  const auxIds = nodes
    .filter(n => meta(n).category === 'Observability' || configSourceIds.has(n.id))
    .map(n => n.id);

  const runOne = async (node) => {
    const m = meta(node);
    onEvent?.({ type: 'start', nodeId: node.id });
    const incoming = dataEdges.find(e => e.target === node.id);
    const inputVal = incoming ? values[incoming.source] : (m.kind === 'input' ? { value: userInput } : null);

    // gather config inputs — multiple sources per slot become an array
    const configs = {};
    for (const ce of configEdges.filter(e => e.target === node.id)) {
      if (values[ce.source] == null) continue;
      if (configs[ce.slot] == null) configs[ce.slot] = values[ce.source];
      else if (Array.isArray(configs[ce.slot])) configs[ce.slot].push(values[ce.source]);
      else configs[ce.slot] = [configs[ce.slot], values[ce.source]];
    }

    const t0 = performance.now();
    try {
      const params = { ...Object.fromEntries((m.params || []).map(p => [p.name, p.default])), ...(node.params || {}) };
      const child = childOf[node.id];
      const out = await m.run(inputVal, params, { ...ctx, configs, child });
      const dt = performance.now() - t0;
      values[node.id] = out;
      onEvent?.({ type: 'success', nodeId: node.id, duration: dt, output: out?.value });
      for (const childId of adj[node.id]) onEvent?.({ type: 'edge', source: node.id, target: childId });
    } catch (err) {
      const dt = performance.now() - t0;
      onEvent?.({ type: 'error', nodeId: node.id, duration: dt, error: err.message || String(err) });
      throw err;
    }
  };

  // Run aux first (they're idempotent handle-returners)
  for (const id of auxIds) {
    if (nestedIds.has(id)) continue;
    const node = nodes.find(n => n.id === id);
    if (node) await runOne(node);
  }

  // Then run main flow in topo order, skipping already-run aux and nested children
  for (const id of order) {
    if (auxIds.includes(id) || nestedIds.has(id)) continue;
    const node = nodes.find(n => n.id === id);
    if (node) await runOne(node);
  }

  const finalNode = nodes.find(n => meta(n).kind === 'output');
  return values[finalNode?.id]?.value ?? '';
}

window.XFlowsEngine = { validate, topoSort, execute, meta };
