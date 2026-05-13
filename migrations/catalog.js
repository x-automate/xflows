// XFlows agentic node catalog — with icons and config slots
// kind: 'input' | 'transform' | 'llm' | 'tool' | 'router' | 'output' | 'aux'
// configs: optional array of { name, accepts: [categoryName, ...], label } — render as bottom ports
window.XFLOWS_ICONS = {
  input:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h12"/><path d="M12 8l4 4-4 4"/><circle cx="20" cy="12" r="1.5" fill="currentColor"/></svg>',
  output:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="4" cy="12" r="1.5" fill="currentColor"/><path d="M8 12h12"/><path d="M16 8l4 4-4 4"/></svg>',
  prompt:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16v12H8l-4 4z"/><path d="M8 9h8M8 12h5"/></svg>',
  openai:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2a4 4 0 0 0-3.46 6 4 4 0 0 0 0 8 4 4 0 0 0 6.92 0 4 4 0 0 0 0-8A4 4 0 0 0 12 2z"/><path d="M12 8v8M8 10l8 4M16 10l-8 4" stroke-width="1.2"/></svg>',
  anthropic:    '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4l-4 16h3l1-4h6l1 4h3L13 4H7zm0 8l2-6 2 6H7zm10-8l4 16h-3l-4-16h3z"/></svg>',
  http:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18"/></svg>',
  search:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
  code:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 6l-4 12"/></svg>',
  vector:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
  sum:          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h14L11 12l8 8H5l8-8L5 4z"/></svg>',
  branch:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="12" r="2"/><path d="M8 6c0 4 8 4 8 6M8 18c0-4 8-4 8-6"/></svg>',
  json:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 4c-2 0-3 1-3 3v3c0 1-1 2-2 2 1 0 2 1 2 2v3c0 2 1 3 3 3M16 4c2 0 3 1 3 3v3c0 1 1 2 2 2-1 0-2 1-2 2v3c0 2-1 3-3 3"/></svg>',
  regex:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v8M8.5 6l7 4M8.5 10l7-4"/><circle cx="6" cy="18" r="2" fill="currentColor"/></svg>',
  agent:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="8" width="12" height="10" rx="2"/><path d="M12 4v4M9 12v2M15 12v2"/><circle cx="3" cy="13" r="1.5"/><circle cx="21" cy="13" r="1.5"/></svg>',
  markdown:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 14V10l2 3 2-3v4M15 10v4M13 12l2 2 2-2"/></svg>',
  trace:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><path d="M12 4v2M12 18v2M4 12h2M18 12h2"/></svg>',
  guard:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></svg>',
  retry:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v5h5"/></svg>',
};

window.XFLOWS_CATALOG = [
  // ---------- I/O ----------
  {
    id: 'Input', name: 'Input', category: 'I/O', kind: 'input', icon: 'input',
    desc: 'User input — entry point of the workflow.',
    params: [],
    async run(_in) { return { value: _in?.value ?? '' }; },
  },
  {
    id: 'Output', name: 'Output', category: 'I/O', kind: 'output', icon: 'output',
    desc: 'Final response shown to the user.',
    params: [],
    async run(input) { return { value: input?.value ?? '' }; },
  },

  // ---------- Prompt ----------
  {
    id: 'PromptTemplate', name: 'Prompt', category: 'Prompt', kind: 'transform', icon: 'prompt',
    desc: 'Render a prompt by substituting {input} with the upstream value.',
    params: [
      { name: 'template', type: 'textarea', default: 'Answer concisely:\n\n{input}' },
      { name: 'system',   type: 'textarea', default: 'You are a helpful assistant.' },
    ],
    async run(input, p) {
      const text = (p.template || '').replace(/\{input\}/g, input?.value ?? '');
      return { value: text, system: p.system };
    },
  },

  // ---------- LLM Container ----------
  {
    id: 'LLM', name: 'LLM', category: 'LLM', kind: 'container', icon: 'agent',
    desc: 'LLM block — drop a provider (OpenAI, Claude) inside it.',
    accepts: ['LLM-Provider'],
    configs: [
      { name: 'tracer', label: 'tracer', accepts: ['Observability'] },
      { name: 'memory', label: 'memory', accepts: ['Memory'] },
      { name: 'tools',  label: 'tools',  accepts: ['Tool'] },
    ],
    params: [],
    async run(input, _p, ctx) {
      const child = ctx.child;
      if (!child) throw new Error('LLM container is empty — drop an OpenAI or Claude provider inside.');
      const meta = window.XFLOWS_CATALOG.find(c => c.id === child.componentId);
      const params = { ...Object.fromEntries((meta.params || []).map(p => [p.name, p.default])), ...(child.params || {}) };
      return meta.run(input, params, ctx);
    },
  },

  // ---------- LLM Providers (drop into LLM container) ----------
  {
    id: 'OpenAIChat', name: 'OpenAI', category: 'LLM-Provider', kind: 'provider', icon: 'openai',
    requiresContainer: 'LLM',
    desc: 'Call an OpenAI chat model.',
    configs: [
      { name: 'tracer', label: 'tracer', accepts: ['Observability'] },
      { name: 'memory', label: 'memory', accepts: ['Memory'] },
    ],
    params: [
      { name: 'model', type: 'select', options: ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'], default: 'gpt-4o-mini' },
      { name: 'temperature', type: 'number', default: 0.7, step: 0.1 },
      { name: 'max_tokens', type: 'number', default: 512 },
    ],
    async run(input, p, ctx) {
      const key = ctx.apiKeys.openai;
      if (!key) throw new Error('Missing OpenAI API key. Add it in the Test tab.');
      const messages = [];
      const extraSys = ctx.configs?.memory?.value;
      const sys = [input?.system, extraSys].filter(Boolean).join('\n\n');
      if (sys) messages.push({ role: 'system', content: sys });
      messages.push({ role: 'user', content: input?.value ?? '' });
      ctx.configs?.tracer?.trace?.({ node: 'OpenAIChat', model: p.model, input: input?.value });
      const res = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${key}` },
        body: JSON.stringify({ model: p.model, temperature: Number(p.temperature), max_tokens: Number(p.max_tokens), messages }),
      });
      if (!res.ok) throw new Error(`OpenAI ${res.status}: ${(await res.text()).slice(0, 200)}`);
      const data = await res.json();
      const out = data.choices?.[0]?.message?.content ?? '';
      ctx.configs?.tracer?.trace?.({ node: 'OpenAIChat', output: out, usage: data.usage });
      return { value: out, usage: data.usage };
    },
  },
  {
    id: 'AnthropicChat', name: 'Claude', category: 'LLM-Provider', kind: 'provider', icon: 'anthropic',
    requiresContainer: 'LLM',
    desc: 'Call Anthropic Claude (uses built-in helper).',
    configs: [
      { name: 'tracer', label: 'tracer', accepts: ['Observability'] },
      { name: 'memory', label: 'memory', accepts: ['Memory'] },
    ],
    params: [
      { name: 'model', type: 'select', options: ['claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4'], default: 'claude-haiku-4-5' },
    ],
    async run(input, p, ctx) {
      const sys = input?.system || '';
      const extraSys = ctx.configs?.memory?.value || '';
      const userText = input?.value ?? '';
      const fullSys = [sys, extraSys].filter(Boolean).join('\n\n');
      ctx.configs?.tracer?.trace?.({ node: 'AnthropicChat', model: p.model, input: userText });
      if (!window.claude?.complete) throw new Error('Anthropic helper unavailable.');
      const out = await window.claude.complete({
        messages: [{ role: 'user', content: fullSys ? `${fullSys}\n\n${userText}` : userText }],
      });
      ctx.configs?.tracer?.trace?.({ node: 'AnthropicChat', output: out });
      return { value: out };
    },
  },

  // ---------- Tools ----------
  {
    id: 'HttpRequest', name: 'HTTP', category: 'Tool', kind: 'tool', icon: 'http',
    desc: 'Make an HTTP GET/POST and return response text.',
    params: [
      { name: 'method', type: 'select', options: ['GET', 'POST'], default: 'GET' },
      { name: 'url', type: 'text', default: 'https://api.example.com/data' },
      { name: 'body_uses_input', type: 'bool', default: true },
    ],
    async run(input, p) {
      const opts = { method: p.method };
      if (p.method === 'POST') {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = p.body_uses_input ? JSON.stringify({ input: input?.value ?? '' }) : '{}';
      }
      const res = await fetch(p.url, opts);
      const text = await res.text();
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 120)}`);
      return { value: text };
    },
  },
  {
    id: 'WebSearch', name: 'Search', category: 'Tool', kind: 'tool', icon: 'search',
    desc: 'Mocked search — returns synthetic results.',
    params: [{ name: 'top_k', type: 'number', default: 3 }],
    async run(input, p) {
      await new Promise(r => setTimeout(r, 400));
      const k = Number(p.top_k) || 3;
      const q = input?.value ?? '';
      const results = Array.from({ length: k }, (_, i) =>
        `[${i + 1}] Result about "${q.slice(0, 40)}" — synthetic snippet ${i + 1}.`
      );
      return { value: results.join('\n') };
    },
  },
  {
    id: 'CodeExec', name: 'Code', category: 'Tool', kind: 'tool', icon: 'code',
    desc: 'Run JS. `input` is the upstream value; return a value.',
    params: [{ name: 'code', type: 'textarea', default: 'return input.toUpperCase();' }],
    async run(input, p) {
      const fn = new Function('input', p.code || 'return input;');
      const out = await fn(input?.value ?? '');
      return { value: typeof out === 'string' ? out : JSON.stringify(out) };
    },
  },

  // ---------- Memory ----------
  {
    id: 'VectorStore', name: 'Vector DB', category: 'Memory', kind: 'aux', icon: 'vector',
    desc: 'Vector retrieval — attach to an LLM as memory.',
    params: [
      { name: 'collection', type: 'text', default: 'docs' },
      { name: 'top_k', type: 'number', default: 3 },
      { name: 'query', type: 'text', default: '' },
    ],
    async run(_in, p) {
      await new Promise(r => setTimeout(r, 200));
      const k = Number(p.top_k) || 3;
      const docs = Array.from({ length: k }, (_, i) =>
        `<doc-${i + 1}> from ${p.collection}: relevant context.`
      );
      return { value: 'Relevant context:\n' + docs.join('\n\n') };
    },
  },
  {
    id: 'Summarizer', name: 'Summarize', category: 'Memory', kind: 'transform', icon: 'sum',
    desc: 'Condense input by truncating.',
    params: [{ name: 'max_chars', type: 'number', default: 200 }],
    async run(input, p) {
      const v = String(input?.value ?? '');
      const m = Number(p.max_chars) || 200;
      return { value: v.length > m ? v.slice(0, m) + '…' : v };
    },
  },

  // ---------- Router ----------
  {
    id: 'IfElse', name: 'If/Else', category: 'Router', kind: 'router', icon: 'branch',
    desc: 'Pass-through with a contains-check; throws on no-match if strict.',
    params: [
      { name: 'contains', type: 'text', default: '' },
      { name: 'mode', type: 'select', options: ['warn', 'fail'], default: 'warn' },
    ],
    async run(input, p) {
      const v = String(input?.value ?? '');
      const matched = p.contains ? v.toLowerCase().includes(p.contains.toLowerCase()) : true;
      if (!matched && p.mode === 'fail') throw new Error(`Input did not contain "${p.contains}"`);
      return { value: v, matched };
    },
  },

  // ---------- Parser ----------
  {
    id: 'JsonParser', name: 'JSON', category: 'Parser', kind: 'transform', icon: 'json',
    desc: 'Parse upstream string as JSON.',
    params: [{ name: 'extract_path', type: 'text', default: '' }],
    async run(input, p) {
      const raw = String(input?.value ?? '');
      const m = raw.match(/```(?:json)?\s*([\s\S]+?)\s*```/);
      const src = m ? m[1] : raw;
      const obj = JSON.parse(src);
      let out = obj;
      if (p.extract_path) for (const seg of p.extract_path.split('.')) out = out?.[seg];
      return { value: typeof out === 'string' ? out : JSON.stringify(out, null, 2) };
    },
  },
  {
    id: 'RegexExtract', name: 'Regex', category: 'Parser', kind: 'transform', icon: 'regex',
    desc: 'Extract first regex match group.',
    params: [
      { name: 'pattern', type: 'text', default: '\\d+' },
      { name: 'flags', type: 'text', default: 'i' },
    ],
    async run(input, p) {
      const re = new RegExp(p.pattern, p.flags || '');
      const m = String(input?.value ?? '').match(re);
      if (!m) throw new Error(`No match for /${p.pattern}/${p.flags}`);
      return { value: m[1] ?? m[0] };
    },
  },

  // ---------- Agent ----------
  {
    id: 'ReActAgent', name: 'ReAct', category: 'Agent', kind: 'llm', icon: 'agent',
    desc: 'Mock ReAct loop.',
    configs: [
      { name: 'tracer', label: 'tracer', accepts: ['Observability'] },
    ],
    params: [
      { name: 'max_steps', type: 'number', default: 3 },
      { name: 'tools', type: 'text', default: 'search,calculator' },
    ],
    async run(input, p, ctx) {
      const steps = Number(p.max_steps) || 3;
      const trace = [];
      for (let i = 1; i <= steps; i++) {
        await new Promise(r => setTimeout(r, 200));
        const step = `Step ${i}: observed "${(input?.value || '').slice(0, 30)}", chose tool from [${p.tools}]`;
        trace.push(step);
        ctx.configs?.tracer?.trace?.({ node: 'ReActAgent', step: i, action: step });
      }
      return { value: trace.join('\n') + `\n\nFinal answer: processed ${input?.value || ''}` };
    },
  },

  // ---------- Format ----------
  {
    id: 'Markdown', name: 'Markdown', category: 'Format', kind: 'transform', icon: 'markdown',
    desc: 'Wrap content in markdown.',
    params: [{ name: 'wrap', type: 'select', options: ['as-is', 'codeblock', 'quote', 'bullets'], default: 'as-is' }],
    async run(input, p) {
      const v = String(input?.value ?? '');
      if (p.wrap === 'codeblock') return { value: '```\n' + v + '\n```' };
      if (p.wrap === 'quote') return { value: v.split('\n').map(l => '> ' + l).join('\n') };
      if (p.wrap === 'bullets') return { value: v.split('\n').filter(Boolean).map(l => '- ' + l).join('\n') };
      return { value: v };
    },
  },

  // ---------- Observability (aux nodes attached via config ports) ----------
  {
    id: 'Tracer', name: 'Tracer', category: 'Observability', kind: 'aux', icon: 'trace',
    desc: 'Logs LLM calls. Connect to an LLM\'s "tracer" config port.',
    params: [
      { name: 'level', type: 'select', options: ['info', 'debug', 'verbose'], default: 'info' },
      { name: 'destination', type: 'select', options: ['console', 'trace-panel', 'both'], default: 'both' },
    ],
    async run(_in, p, ctx) {
      // Returns a trace handle the consuming node can call.
      return {
        trace(event) {
          const msg = `[trace:${p.level}] ${JSON.stringify(event).slice(0, 180)}`;
          if (p.destination !== 'trace-panel') console.log(msg);
          ctx.onTrace?.(msg);
        },
      };
    },
  },
  {
    id: 'Guardrail', name: 'Guardrail', category: 'Observability', kind: 'aux', icon: 'guard',
    desc: 'Blocks output if it contains forbidden terms. Connect to LLM tracer.',
    params: [
      { name: 'forbidden', type: 'text', default: 'password,secret' },
    ],
    async run(_in, p) {
      const banned = (p.forbidden || '').split(',').map(s => s.trim()).filter(Boolean);
      return {
        trace(event) {
          if (event.output) {
            for (const b of banned) {
              if (event.output.toLowerCase().includes(b.toLowerCase())) {
                throw new Error(`Guardrail blocked output: contains "${b}"`);
              }
            }
          }
        },
      };
    },
  },
];

window.CATEGORY_COLORS = {
  'I/O':           { fg: '#1f2937', bg: '#f1f5f9', dot: '#475569' },
  'Prompt':        { fg: '#6b3aa0', bg: '#f3eafd', dot: '#8b5cf6' },
  'LLM':           { fg: '#0f766e', bg: '#e6fbf6', dot: '#14b8a6' },
  'LLM-Provider':  { fg: '#0f766e', bg: '#ccfbf1', dot: '#0d9488' },
  'Tool':          { fg: '#9a3412', bg: '#fff1e6', dot: '#f97316' },
  'Memory':        { fg: '#1e40af', bg: '#e8efff', dot: '#3b82f6' },
  'Router':        { fg: '#854d0e', bg: '#fef7c8', dot: '#eab308' },
  'Parser':        { fg: '#155e75', bg: '#e3f6fb', dot: '#06b6d4' },
  'Agent':         { fg: '#9f1239', bg: '#ffe9ee', dot: '#e11d48' },
  'Format':        { fg: '#475569', bg: '#eef2f7', dot: '#64748b' },
  'Observability': { fg: '#7c2d12', bg: '#fef3e2', dot: '#c2410c' },
};

window.SKLEARN_CATALOG = window.XFLOWS_CATALOG;
