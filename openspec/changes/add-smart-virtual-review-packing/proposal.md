## Why

The first virtual-review version makes one atomic task visible at a time, which is precise but can require excessive page turns when a 25–30-object image contains several spatially compatible targets. The second stage should reduce navigation overhead without shrinking targets below an editable screen size or reintroducing selection ambiguity.

## What Changes

- Add a deterministic smart-packing layer above the existing atomic `VirtualTask` list.
- Keep each valid `group_id` task indivisible and pack one or more atomic tasks into a `VirtualReviewPage` only when screen-size and separation constraints remain safe.
- Add single-task, balanced, and high-density display modes with a conservative maximum task count per page.
- Navigate virtual pages with the existing F2 / Shift+F2 actions; all page members remain normally visible and editable while non-page shapes remain dim and non-interactive.
- Show task-to-page packing statistics and current page/task counts in the Inspector.
- Freeze generated pages until explicit regeneration or image load, and fall back to singleton pages whenever no safe combination exists.
- Keep the stage current-image-only and transient: no cross-file queue, persisted review progress, model prediction, physical split files, or annotation-JSON metadata.

## Capabilities

### New Capabilities

- `smart-virtual-review-packing`: Defines deterministic geometry-based packing of atomic virtual-review tasks into editable pages, packing controls, navigation, fallback behavior, and lifecycle guarantees.

### Modified Capabilities

- None.

## Impact

- Extends the pure-Python `virtual_review` package with page, packing-option, geometry-evaluation, and packing-result models.
- Changes the virtual-review session/controller from task navigation to page navigation while retaining atomic task membership and runtime identities.
- Extends the Inspector target-review tab with packing mode, density controls, and page statistics.
- Reuses the existing Canvas virtual-focus predicate and viewport controller; no annotation schema or external dependency changes are required.
