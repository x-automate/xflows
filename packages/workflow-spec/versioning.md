# Workflow Versioning Strategy

## Lifecycle States

- `draft`: Editable state. Can be tested and iterated.
- `published`: Immutable executable version used by production runs.
- `archived`: Non-executable historical version.

## Rules

1. New workflows start at `version=1` in `draft`.
2. Publishing clones the current draft into an immutable `published` version and
   increments the draft version number.
3. Runs always reference a concrete workflow id and published version.
4. Existing runs must never be affected by future edits.
5. Archived versions are retained for audit and replay.

## Compatibility Guidance

- Additive changes to node params are backward compatible.
- Removing node ids, changing component semantics, or changing edge behavior
  requires a new published version.
- Worker activities should include feature flags to preserve deterministic replay
  for old workflow versions.
