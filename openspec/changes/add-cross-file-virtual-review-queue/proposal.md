## Why

The first two virtual-review stages reduce visual overload within one image, but reviewers still have to choose files manually and lose their place when the application closes. A dataset-level queue and an external progress ledger are now needed to turn the feature into a resumable quality-review workflow without contaminating annotation JSON.

## What Changes

- Build a deterministic cross-file queue from the currently loaded dataset, the existing virtual-task criteria, and the existing page-packing options.
- Navigate the queue across image boundaries while preserving the normal dirty-file save/discard/cancel guard before every transition.
- Persist queue definition, cursor, per-task review state, timestamps, and reconciliation diagnostics in a reviewer-selected, versioned SQLite sidecar; never write review metadata into annotation JSON.
- Support explicit review outcomes `pending`, `completed`, `needs_rework`, and `skipped`, with completion recorded only by a deliberate review action rather than by merely visiting a page.
- Resume an existing queue after restart, skip completed work by default, and let the reviewer include completed or unresolved items through filters.
- Reconcile a frozen queue against changed, moved, missing, or newly added annotation files without silently transferring progress to an ambiguous target.
- Commit progress transactionally after each outcome change and cursor transition, recover safely from interrupted writes, and expose queue statistics and reconciliation warnings.
- Keep page membership within a single image. Cross-file queue entries point to image-local pages; no page combines shapes from different files.

## Capabilities

### New Capabilities

- `cross-file-virtual-review-queue`: Defines dataset discovery, deterministic image/page queue construction, cross-file navigation, file-transition safety, queue freezing, reconciliation, and lifecycle behavior.
- `virtual-review-progress-persistence`: Defines stable external identities, review states, atomic sidecar persistence, restart recovery, schema versioning, conflict handling, and progress summaries.

### Modified Capabilities

None. This stage layers dataset-level orchestration above the existing image-local virtual-task and smart-packing capabilities.

## Impact

- Extends the pure-Python `virtual_review` package with queue, locator, progress, storage, and reconciliation models/services.
- Extends the Inspector target-review tab with queue creation/opening, state actions, filters, counters, and recovery warnings.
- Extends `VirtualReviewController` and narrow `LabelWidget` integration points to request guarded file transitions and react to successful or cancelled loads.
- Adds a versioned `.xreview.sqlite3` sidecar selected by the user, using Python's standard SQLite support; annotation JSON schema and physical dataset layout remain unchanged.
- Adds pure-Python queue/persistence/reconciliation tests and focused offscreen Qt workflow tests. No new runtime dependency is required.
