# XFlows Web App

This directory contains the production frontend application.

## Responsibilities

- Workflow authoring UI and graph editor
- Run launch, cancellation, and event streaming UI
- Environment-aware API client integration
- Zero provider secrets in the browser

## Migration Notes

POC files from repository root should be migrated into this app incrementally:

## Migration Status Matrix

- `app.jsx` -> `src/features/workflow/AppShell.jsx` (ported, backend run flow enabled)
- `component-panel.jsx` -> `src/features/workflow/components/ComponentPanel.jsx` (ported)
- `canvas.jsx` -> `src/features/workflow/components/Canvas.jsx` (ported)
- `steps-pane.jsx` -> `src/features/workflow/components/StepsPane.jsx` (ported, backend events)
- `param-modal.jsx` -> `src/features/workflow/components/ParamModal.jsx` (ported)
- `styles.css` -> `src/features/workflow/workflow.css` (ported with `wf-` namespace)
- `catalog.js` -> `src/features/workflow/catalog/catalog-meta.js` (frontend metadata only)
- `codegen.js` -> `src/lib/api/workflowApi.js` + backend orchestration (browser execution removed)

## Remaining Follow-ups

- Improve event-to-node mapping once worker emits stable `nodeId`-based payloads for all run modes.
- Add dedicated run history page backed by `/runs/{id}` query views.
- Add integration tests for workflow editor parity scenarios.
