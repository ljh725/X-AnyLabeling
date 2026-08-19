## Context

The first-stage virtual review already produces frozen, deterministic `VirtualTask` units, where a valid `group_id` expands to all same-group shapes and an ungrouped anchor becomes one single-shape task. `VirtualReviewSession` currently navigates tasks directly, and the Qt controller installs one task's runtime identities into the Canvas virtual-focus predicate.

Second-stage packing must build above those task semantics rather than replacing them. It must also resolve the distance trade-off: tasks that are too close reintroduce visual and hit-test ambiguity, while tasks that are very far apart create a large union box and shrink every target during viewport fitting. Screen-space editability after fitting is therefore a stronger safety measure than image-space centre distance alone.

## Goals / Non-Goals

**Goals:**

- Keep `VirtualTask` as the indivisible review unit and add a page layer above it.
- Use deterministic, independently testable geometry rules to reduce page turns.
- Express safety in projected screen pixels so behavior follows the actual review viewport.
- Preserve first-stage rendering, interaction, viewport restoration, undo, save, and frozen-session guarantees.
- Make singleton fallback universal so packing never loses a review task.

**Non-Goals:**

- Machine-learned or quality-model-driven task pairing.
- Splitting one `group_id` task across pages.
- Cross-image packing, persistent review progress, or dataset-level queues.
- Automatically changing labels, geometry, or group ids.
- Replacing Canvas virtual focus or the existing viewport state machine.

## Decisions

### Decision 1: Add pages above atomic tasks

Add immutable `VirtualReviewPage`, `VirtualPackingOptions`, and `VirtualPackingResult` models. A page references ordered atomic task ids, contains the union member ids and bbox needed by the controller, and records projected geometry useful for UI diagnostics.

The builder remains a two-step pipeline:

```text
Shape views -> build_virtual_tasks() -> pack_virtual_tasks() -> pages
```

This avoids duplicating label/group/size criteria inside the packing layer and ensures a group is never split accidentally. The alternative—building combined pages directly from shapes—was rejected because it couples anchor filtering, group expansion, and page geometry into one difficult-to-test algorithm.

### Decision 2: Use projected screen-space hard gates

For a tentative page union bbox and viewport `(Vw, Vh)`, compute a padded fit scale:

```text
scale = min(Vw / (union_width * margin),
            Vh / (union_height * margin))
```

For each atomic task anchor:

```text
projected_short_side = min(anchor_width, anchor_height) * scale
```

For each pair of atomic task bboxes:

```text
projected_gap = image_space_bbox_gap * scale
```

A candidate passes only if every projected anchor short side meets `min_projected_anchor_px`, every pairwise projected gap meets `min_projected_gap_px`, and the page task count does not exceed `max_tasks_per_page`. Missing/invalid geometry fails closed to singleton output.

This replaces a pure relative-distance rule. A maximum image-space centre distance was considered but rejected because it does not account for viewport dimensions, target sizes, or aspect ratio.

### Decision 3: Provide named presets backed by explicit options

Use three modes:

- `single`: maximum one task; geometry gates are irrelevant.
- `balanced`: default maximum two tasks with conservative projected-size and gap thresholds.
- `dense`: default maximum three tasks with lower, still positive thresholds.

The UI shows the effective values and permits adjustment before regeneration. Initial code constants provide starting values, but the algorithm consumes explicit validated options rather than branching on preset names. This lets future usability testing tune defaults without rewriting the packer.

### Decision 4: Use deterministic seed-and-grow packing

Iterate atomic tasks in their existing order. The first unassigned task seeds a page. Evaluate all remaining candidates against the full tentative page. Among candidates that pass hard gates, rank by:

1. largest worst-case projected anchor short side;
2. smallest normalized union area;
3. earliest original anchor/task order.

Add the best candidate and repeat until the page limit is reached or no candidate passes. Then freeze the page and continue with the next unassigned task.

Global optimization and graph partitioning were rejected for this phase. They can reduce pages marginally but make results harder to explain, reproduce, and tune. The greedy method is deterministic, bounded, and adequate for approximately 25–30 objects per image.

### Decision 5: Navigate one uniform page model in every mode

The controller and session navigate pages, including in single-task mode where each page wraps exactly one task. This avoids maintaining parallel task-mode and page-mode code paths. `VirtualReviewSession` should either become generic over page-like items or receive a page-specific replacement while preserving its boundary and deleted-anchor semantics.

The page focus predicate is the union of all current page member ids. Anchor selection remains deterministic: select the first surviving task anchor as the primary selection, while all current-page members remain interactive.

### Decision 6: Freeze pages and rebuild only at explicit lifecycle points

Page membership is frozen after generation. Repacking occurs only when the user explicitly regenerates or after a successful image load while review mode remains active. Window resize and shape edits may change the actual fitted scale but do not silently change membership.

This preserves cursor stability. A possible automatic resize repack was rejected because it could change the current page while the user is editing.

### Decision 7: Keep packing pure and Qt adaptation thin

Geometry, validation, compatibility evaluation, scoring, and packing live in the pure-Python `virtual_review` package. Qt code supplies viewport dimensions, renders page statistics, installs member predicates, and fits the page bbox. This maintains the existing test boundary and avoids importing PyQt into core packing tests.

## Risks / Trade-offs

- **[Preset thresholds do not match every monitor or annotation type]** -> Expose effective values, keep them configurable, and retain single-task mode as an immediate fallback.
- **[Greedy packing is not globally optimal]** -> Optimize for deterministic explainability and safe page reduction; record packing statistics so later evidence can justify a more complex solver.
- **[One large atomic group already has a large bbox]** -> Never split the group; emit it as a singleton even if it fails normal projected-size expectations.
- **[Window resize can make a frozen page less comfortable]** -> Refit the same membership and provide explicit regeneration; do not silently repack during editing.
- **[Deleted anchors can invalidate part of a page]** -> Drop missing members at activation, select the first surviving page anchor, and skip a page only when no task anchor survives.
- **[Adding multiple editable tasks can increase accidental selection]** -> Enforce projected gaps, keep non-page shapes non-interactive, and default to a maximum of two tasks.

## Migration Plan

No annotation migration is required. Existing one-task sessions map to singleton pages. Ship balanced mode conservatively, preserve an explicit single-task option, and roll back by selecting single mode or removing the packing UI/builder while leaving first-stage `VirtualTask` generation unchanged.
