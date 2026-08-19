## Context

The existing `FilterState`/`ShapeFilterEngine` handles label, group-id, and shape-type visibility, but it mutates base visibility and has no size or task-session concept. The Canvas also has an existing focus predicate used by three-box refinement. The new review flow must compose with these layers without changing `hidden_by_filter`, triggering a full quality scan on every page turn, or persisting temporary task state.

## Goals / Non-Goals

**Goals:**

- Add a pure-Python criteria, grouping, and session layer that is independently testable.
- Add one-task-at-a-time review UI for the current image.
- Preserve base visibility, existing F1 behavior, undo/autosave, and image-change guards.
- Provide a separate virtual-focus render/interaction layer and transient viewport control.

**Non-Goals:**

- Spatial multi-task page packing.
- Cross-dataset task persistence or normalized size criteria.
- Automatic inference or writing of missing group ids.
- Replacing the existing filter engine or three-box focus controller.

## Decisions

### Decision 1: Separate virtual criteria from FilterState

Create `VirtualTaskCriteria` rather than extending `FilterState`. The existing state controls persistent shape/dataset visibility; virtual criteria only select anchors for a temporary review session. This avoids changing filtered data, inspector behavior, or quality-review eligibility.

### Decision 2: Group by valid group id, with single-shape fallback

The task builder first filters anchors, then expands each valid group id to all same-group shapes. It keys ungrouped tasks by a runtime shape identity. Group tasks are deduplicated by group id and ordered by the first matching shape’s original order.

### Decision 3: Use runtime identity that survives undo copies

Shapes receive a non-serialized runtime virtual-review identity when needed. `Shape.copy()` already uses deepcopy, so the identity survives undo snapshots without entering `Shape.to_dict()` or the JSON file.

### Decision 4: Add a separate Canvas task-focus layer

Canvas keeps `base_visible()` and the existing main focus predicate. A virtual task predicate is added as a separate transient layer. Current members pass normal paint and interaction; base-visible non-members receive a dim context pass and fail the normal interaction gate. Changing this layer only repaints and does not publish a full shape-change notification.

### Decision 5: Use a thin Qt controller and an Inspector tab

Pure task/session logic lives under `virtual_review/`. A Qt controller owns Canvas, viewport, image-load, and selection integration. A new Inspector “目标复核” tab edits criteria and exposes start/rebuild/exit/overview controls. `LabelWidget` only wires lifecycle and actions instead of owning the task algorithm.

### Decision 6: Preserve F1 and use F2/Shift+F2

F1 is already the digit-shortcut page action. Default virtual navigation is therefore `F2` next and `Shift+F2` previous. The shortcuts are registered through the existing settings schema and conflict validator.

### Decision 7: Freeze task membership and order per image

The session snapshots task ids and member ids at generation time. Edits do not cause silent reordering. A new image rebuilds tasks from the active criteria; explicit “重新生成任务” is required for the current image.

### Decision 8: Reuse viewport capture/apply primitives

The controller captures the pre-session viewport through `ViewportController`, computes a padded union bbox for the active task, and applies a transient center/zoom. On exit it restores the captured state and does not commit the transient state as the image’s persisted viewport.

### Decision 9: Make conflicting focus modes explicit

Starting virtual review clears the three-box focus predicate and suppresses Pose click-to-focus while the session is active. The virtual group focus is the single active task focus. Existing base filters remain intact.

## Risks / Trade-offs

- **[F2 can be triggered during an edit gesture]** → Ignore navigation while drawing, dragging, or a modal editor is active; show a status hint.
- **[Runtime shape identities can be absent after legacy construction]** → Lazily assign identities and skip invalid/deleted task members safely.
- **[Dim context adds a paint pass]** → Restrict the pass to active virtual-review mode and avoid rebuilding labels or quality overlays on each page turn.
- **[Existing focus observers expect notifications]** → Keep the existing notification behavior for the three-box predicate; the new virtual predicate uses repaint-only updates.
- **[Users may expect F1/F2 pair]** → Surface the occupied F1 binding in settings/help and allow explicit user remapping through the existing conflict validator.

## Migration Plan

No annotation-data migration is required. Add conservative default settings with virtual review inactive. Enable the mode per session, and roll back by removing the new tab/actions/controller while leaving existing JSON and visibility fields untouched.
