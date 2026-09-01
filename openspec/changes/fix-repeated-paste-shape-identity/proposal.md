## Why

The in-memory annotation clipboard reuses the same `Shape` instances on every paste. Pasting twice on one image therefore inserts duplicate object references into the Canvas, violates the live-shape identity invariant, and raises `ValueError: Current shape snapshot contains duplicate objects` from rectangle-size monitoring.

## What Changes

- Treat the in-memory copied-shape collection as reusable templates rather than live Canvas objects.
- Materialize a fresh `Shape` instance with a fresh persistent shape identity for every pasted annotation, including rapid repeated pastes and pastes after image navigation.
- Reject duplicate live object references before an append mutates annotation UI state; do not silently deduplicate, suppress a requested paste, or weaken the monitor invariant.
- Add regression coverage for repeated same-image paste, cross-image paste, multi-shape paste, identity uniqueness, and rectangle-size monitor integration.

## Capabilities

### New Capabilities

- `annotation-clipboard-paste`: Defines repeatable in-memory annotation paste behavior, fresh object and persistent identities per paste, cross-image clipboard reuse, and pre-mutation identity safety.

### Modified Capabilities

- None.

## Impact

- Affected code: `anylabeling/views/labeling/label_widget.py`, the Canvas append boundary in `anylabeling/views/labeling/widgets/canvas.py` or a narrowly shared preflight helper, and focused tests.
- Preserved behavior: system-clipboard paste, cross-image clipboard persistence, shared `Shape` references between the label list and Canvas for each newly created annotation, group metadata, and rectangle-size monitor fail-fast checks.
- No new dependencies, file-format changes, public API changes, or migration requirements.
