// XFlows tweaks — small floating panel for canvas density/theme
function XFlowsTweaks() {
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "accent": "#3b82f6",
    "configAccent": "#c2410c",
    "nodeShadow": true,
    "showCategoryLabel": true,
    "edgeStyle": "curved",
    "canvasBg": "#fafafa"
  }/*EDITMODE-END*/;
  const [t, setTweak] = window.useTweaks(TWEAK_DEFAULTS);

  React.useEffect(() => {
    const r = document.documentElement.style;
    r.setProperty('--xf-accent', t.accent);
    r.setProperty('--xf-config-accent', t.configAccent);
    r.setProperty('--xf-node-shadow', t.nodeShadow ? '2px 2px 0 #111' : 'none');
    r.setProperty('--xf-canvas-bg', t.canvasBg);
    document.body.classList.toggle('xf-no-cat', !t.showCategoryLabel);
    document.body.classList.toggle('xf-edge-straight', t.edgeStyle === 'straight');
  }, [t]);

  return (
    <window.TweaksPanel title="Tweaks">
      <window.TweakSection label="Theme" />
      <window.TweakColor label="Accent" value={t.accent}
        options={['#3b82f6', '#10b981', '#8b5cf6', '#ef4444']}
        onChange={(v) => setTweak('accent', v)} />
      <window.TweakColor label="Config edge" value={t.configAccent}
        options={['#c2410c', '#0d9488', '#7c3aed', '#db2777']}
        onChange={(v) => setTweak('configAccent', v)} />
      <window.TweakColor label="Canvas bg" value={t.canvasBg}
        options={['#fafafa', '#f5f5f4', '#f1f5f9', '#0e1116']}
        onChange={(v) => setTweak('canvasBg', v)} />
      <window.TweakSection label="Nodes" />
      <window.TweakToggle label="Hard shadow" value={t.nodeShadow}
        onChange={(v) => setTweak('nodeShadow', v)} />
      <window.TweakToggle label="Show category" value={t.showCategoryLabel}
        onChange={(v) => setTweak('showCategoryLabel', v)} />
      <window.TweakSection label="Edges" />
      <window.TweakRadio label="Style" value={t.edgeStyle}
        options={['curved', 'straight']}
        onChange={(v) => setTweak('edgeStyle', v)} />
    </window.TweaksPanel>
  );
}

window.XFlowsTweaks = XFlowsTweaks;
