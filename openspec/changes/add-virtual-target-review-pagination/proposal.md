## Why

Data quality review is slow when one image contains 25–30 labeled objects. Physical splitting reduces visual clutter but duplicates dataset files and requires a merge step, while precise rectangle editing remains difficult when unrelated shapes can still be selected. The application needs a reversible, in-memory task view that keeps the original image and JSON authoritative.

## What Changes

- Add an in-application virtual review session for the current image.
- Filter anchor shapes by label, shape type, group-id state/value, and pixel width/height ranges.
- Build one review task per valid group id, including all same-group members; keep ungrouped anchors as single-shape tasks.
- Show one task group at a time, dim unrelated base-visible shapes, and prevent unrelated shapes from mouse interaction.
- Add stable previous/next task navigation without requiring a full-image view between tasks.
- Preserve the existing F1 digit-shortcut pagination and bind virtual review navigation to F2 / Shift+F2 by default.
- Keep edits in the existing in-memory Shape/undo/save flow; do not write virtual-task metadata or create split files.

## Capabilities

### New Capabilities

- `virtual-target-review`: Defines virtual task criteria, task grouping, task-session navigation, focused rendering, and lifecycle behavior.

### Modified Capabilities

- None.

## Impact

- New pure-Python task/session modules and PyQt review-panel/controller integration.
- Canvas receives an independent virtual-focus rendering and interaction layer that does not mutate base filter visibility.
- Labeling settings gain configurable previous/next virtual-review shortcuts; F1 remains unchanged.
- Existing image loading, viewport, undo, autosave, inspector, and quality-review flows must remain compatible.
