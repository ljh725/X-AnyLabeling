## Context

The Canvas exposes a base visibility layer and a focus-aware main visibility
layer. `is_shape_interactive()` intentionally follows the latter. The
rectangle-size controller currently injects that interaction predicate into
the monitor, and Canvas warning construction repeats the same interaction
check. As a result, focus affects both stored review issues and painted
warnings.

The affected Canvas file already contains unrelated uncommitted rectangle-edge
editing work. Implementation must use a narrow patch outside those changed
hunks and preserve the existing working tree.

## Goals / Non-Goals

**Goals:**

- Give rectangle-size review an explicit base-visibility dependency.
- Keep evaluator results and warning-overlay construction consistent.
- Preserve current visibility, rule, persistence, and focus interaction
  behavior outside this coupling.
- Add regression coverage for the exact multi-rule failure sequence.

**Non-Goals:**

- Changing `trigger_mode`, threshold equality, or label matching semantics.
- Changing three-box grouping, focus membership, or interaction behavior.
- Renaming the exported `RectangleCandidate.interactive` field in this fix.
- Changing configuration or translation resources.

## Decisions

### Inject a review predicate based on Canvas base visibility

The monitor callback will be named for review eligibility and the controller
will inject `Canvas.base_visible`. This makes the architectural dependency
explicit and keeps base visibility testable without importing Canvas into the
monitor.

Passing `base_visible` through the old `is_shape_interactive` parameter was
rejected because it would fix behavior while preserving the misleading API
that caused the coupling. Scanning every shape unconditionally was rejected
because it would regress user and filter visibility behavior.

### Keep the candidate compatibility field for this change

The monitor will place the review predicate result into the existing candidate
boolean consumed by the evaluator. Renaming the exported dataclass field would
increase compatibility and test churn without improving this behavioral fix.
A later compatibility-reviewed cleanup may rename it.

### Apply base visibility again at paint time

Canvas will use `base_visible` when converting stored issues into warning
overlay requests. The paint-time guard remains necessary to prevent stale
warnings during the short interval before a monitor refresh after visibility
changes, but it must use the same policy as evaluation.

Removing the paint guard was rejected because asynchronous/debounced updates
could briefly paint warnings for shapes that have become hidden or detached.

### Preserve focus notifications

Installing a focus predicate will continue emitting the generic full-shape
notification. Other observers may rely on the notification. The monitor may
perform a redundant scan, but issue deduplication prevents an unchanged result
from being republished.

## Risks / Trade-offs

- [Warnings may remain visible while their normal shapes are focus-suppressed]
  → This is the required global-review behavior; regression tests will make the
  choice explicit.
- [Renaming the monitor callback can affect direct internal callers] → Update
  all repository callers and tests in the same change, while leaving the
  exported candidate field unchanged.
- [Existing Canvas work could be overwritten] → Patch only the violation
  overlay predicate line and verify the final diff against the pre-existing
  rectangle-edge hunks.
- [Focus changes still cause a full review scan] → Keep current notification
  behavior for compatibility; performance optimization is outside this fix.

## Migration Plan

No persisted-data migration is required. Apply the monitor/controller/Canvas
changes atomically with their regression tests. Rollback consists of reverting
only this isolated change; existing configurations remain valid.
