## Context

See `proposal.md` for motivation and `specs/annotation-clipboard-paste/spec.md` for the behavioral contract. The in-memory clipboard currently stores deep-copied `Shape` instances, but `paste_selected_shape()` passes that same stored list to append loading on every invocation. The first paste therefore changes the practical ownership of those instances from clipboard templates to Canvas objects, while later pastes reuse them as if they were still templates.

`LabelingWidget.load_shapes()` adds each incoming object to the label list before `Canvas.load_shapes()` appends it. Canvas identity normalization repairs persistent `xanylabeling_shape_id` collisions in place but intentionally does not clone objects. Rectangle-size monitoring indexes current shapes by Python object identity and correctly requires each live object to occur only once.

## Goals / Non-Goals

**Goals:**

- Give every paste invocation a fresh batch of `Shape` objects and persistent shape identities.
- Preserve clipboard reuse across image navigation and preserve current copied annotation fields and grouping metadata.
- Detect invalid object-reference append requests before either the label list or Canvas is mutated.
- Keep valid repeated paste compatible with identity normalization, backups, dirty tracking, behavior analytics, and rectangle-size monitoring.

**Non-Goals:**

- Do not throttle, debounce, or discard rapid paste commands.
- Do not silently deduplicate annotations or catch and ignore monitor invariant failures.
- Do not redesign serialization, group-id allocation, undo/redo, or the general file-loading pipeline.
- Do not change existing system-clipboard JSON format or annotation file format.

## Decisions

### Treat the in-memory clipboard as immutable templates

Each non-system-clipboard paste will call the existing canonical `Shape.copy_for_new_object()` operation for every stored template and pass the resulting materialized list to the existing append path. `_copied_shapes` remains reusable clipboard state and never becomes Canvas-owned state.

This is preferred over clearing the clipboard after paste because users need repeated and cross-image paste. It is preferred over throttling because two rapid paste commands represent two requested batches. It is preferred over reusing objects and only changing `xanylabeling_shape_id` because changing a field cannot change Python object identity.

### Keep cloning at the paste ownership boundary

The paste controller owns the semantic decision that a paste creates new annotations. Canvas will not automatically clone collisions: doing so after the label list has received the original objects could make the two views refer to different instances, and automatic cloning would hide caller bugs.

System-clipboard paste continues to deserialize fresh objects per invocation. Both clipboard modes converge on the same append semantics after materialization.

### Add a reusable pre-mutation identity preflight

A narrow preflight will materialize the incoming iterable once and validate live-object identities. Incoming references must be unique. For `replace=False`, none may already be present in `canvas.shapes`. For `replace=True`, overlap with the previous Canvas snapshot remains permitted because replacement and reorder workflows can legitimately reuse current objects, but duplicates within the replacement snapshot remain invalid.

The LabelingWidget wrapper will run the preflight before adding label-list items, and Canvas will enforce the same precondition for direct callers before resetting overlay state, normalizing persistent IDs, storing backups, or mutating `self.shapes`. The implementation should share the validation logic rather than maintain subtly different rules.

Persistent-ID collisions remain the responsibility of existing identity normalization; live-object collision validation must not replace or weaken that behavior.

### Preserve downstream invariant checks

`RectangleSizeMonitor.replace_shapes()` will retain its duplicate-object assertion as a final consistency check. A valid paste must never rely on catching that exception. Behavior analytics and dirty tracking will use the actual materialized paste batch count so one event is recorded for each newly created annotation.

## Risks / Trade-offs

- [Deep-copy cost for large selections or complex polygons] → Reuse the existing `copy_for_new_object()` path, keep work proportional to annotations the user requested, and add a focused repeated multi-shape test without introducing speculative caching.
- [Copied transient fields such as selection or visibility leak into new annotations] → Verify pasted state in regression tests and rely on the same canonical copy operation already used by Canvas duplication; reset only fields whose existing copy contract requires it.
- [Preflight rejects a legacy caller that intentionally appends an existing object] → Limit current-Canvas collision checks to `replace=False`, identify failing callers with targeted tests, and require callers that create annotations to materialize new objects explicitly.
- [Label list and Canvas become inconsistent if validation happens too late] → Run shared preflight before label-list mutation and enforce it again at the Canvas boundary for direct callers.
- [Copied group IDs collide with groups already present on a target image] → Preserve current group metadata semantics in this change; group-id remapping is a separate product decision and is not silently introduced here.
- [Additional guard code duplicates the monitor check] → Treat preflight as an atomicity guard and the monitor check as a downstream consistency assertion; keep both because they protect different failure stages.

## Migration Plan

No persisted-data migration is required. Deploy the source change and focused regression tests together. Rollback consists of reverting the paste materialization and preflight changes; no annotation file format or user configuration is changed.
