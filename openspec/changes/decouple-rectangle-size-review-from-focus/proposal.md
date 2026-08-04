## Why

Rectangle-size violations currently disappear when three-box focus excludes a
shape from interaction. This makes a global, read-only review feature depend on
the user's current edit focus and causes unrelated violations to vanish after
rule changes or anchor selection.

## What Changes

- Make rectangle-size review eligibility depend on the canvas base visibility
  layer instead of the focus-aware interaction layer.
- Keep three-box focus responsible only for main-canvas interaction and normal
  shape presentation.
- Apply the same base-visibility policy during evaluation and violation-overlay
  construction so stored issues and painted warnings cannot disagree.
- Preserve existing behavior for shapes hidden by user visibility controls,
  per-shape visibility, or dataset filters.
- Add regression coverage for focus activation, anchor changes, rule changes,
  and base-hidden shapes.

## Capabilities

### New Capabilities

- `rectangle-size-review-visibility`: Defines which shapes participate in
  rectangle-size review and how review warnings coexist with three-box focus.

### Modified Capabilities

None.

## Impact

- Affected runtime components: rectangle-size controller, monitor, evaluator
  adapter contract, and Canvas violation-overlay filtering.
- Affected tests: rectangle-size end-to-end, monitor/controller, Canvas change
  notification, overlay, and three-box focus integration tests.
- No configuration schema, persistence format, translation, or external
  dependency changes are required.
