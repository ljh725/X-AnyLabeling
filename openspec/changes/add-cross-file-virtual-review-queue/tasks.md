## 1. Queue Models and SQLite Foundation

- [x] 1.1 Add pure-Python queue, revision, source-file, atomic-task, page-binding, outcome, freshness, availability, cursor, and summary models under `virtual_review`, with public exports and validation.
- [x] 1.2 Add canonical serialization for criteria, packing options, relative paths, normalized group ids, member snapshots, and task-content signatures.
- [x] 1.3 Define the initial `.xreview.sqlite3` schema, foreign keys, query indexes, schema-version metadata, and migration registry.
- [x] 1.4 Implement sidecar create/open/close paths with SQLite pragmas, schema validation, `integrity_check`, `foreign_key_check`, and unsupported-newer-version rejection.
- [x] 1.5 Implement transactional revision, source, task, page, page-task, cursor, event, and reconciliation repositories without importing PyQt.
- [x] 1.6 Implement SQLite online backup, pre-migration backup, migration history, WAL checkpoint-on-close, and recovery diagnostics.
- [x] 1.7 Implement the database writer lease, heartbeat, same-host stale-owner checks, read-only fallback, explicit takeover, and optimistic logical-revision verification.
- [x] 1.8 Add pure-Python tests for schema creation, round trips, constraints, transaction rollback, version rejection/migration, backup, lease conflict, stale takeover, and unexpected-revision blocking.

## 2. Stable Task Locators and Reconciliation

- [x] 2.1 Add grouped and ungrouped persistent locator snapshots that remain separate from runtime shape ids and include ordinals, labels, shape types, normalized geometry, group structure, and member fingerprints.
- [x] 2.2 Implement the unchanged-file fast path with stored ordinal and exact fingerprint verification.
- [x] 2.3 Implement exact normalized-group and exact member-fingerprint reconciliation for changed files.
- [x] 2.4 Implement conservative high-confidence candidate scoring with hard shape-type compatibility, normalized geometry/group evidence, a confidence threshold, and a winner margin.
- [x] 2.5 Classify bindings as ready, changed-but-resolved, missing, orphaned, or ambiguous, and ensure ambiguous candidates never receive automatic progress transfer.
- [x] 2.6 Implement explicit manual binding records and relative-root rebinding without editing annotation JSON.
- [x] 2.7 Implement per-task reviewed signatures and freshness evaluation so unrelated file edits stay fresh while changed completed targets become stale.
- [x] 2.8 Add unit tests for label edits, group-id edits, geometry edits, repeated nearby objects, missing files, moved roots, ambiguous matches, manual binding, and per-task freshness.

## 3. Cancellable Queue Construction and Revision Publishing

- [x] 3.1 Define a frozen build request containing ordered dataset file descriptors, effective label paths, validated criteria, validated packing options, reference viewport, and target sidecar path.
- [x] 3.2 Implement sequential per-file JSON loading into scan-local shape views, atomic task building, image-local smart packing, persistent locator creation, and deterministic global ordering.
- [x] 3.3 Enforce that each page contains exactly one source file, omit zero-match files, and collect parse/missing-file exclusions as draft diagnostics.
- [x] 3.4 Implement staging-database construction with progress callbacks, cooperative cancellation, batched transactions, and cleanup that never changes the active queue.
- [x] 3.5 Validate staging schema, integrity, foreign keys, counts, unique membership, and deterministic ordering before publication.
- [x] 3.6 Publish a new queue by installing the validated staging database and publish rebuilds by importing a candidate revision and flipping `active_revision` transactionally.
- [x] 3.7 Add a Qt worker adapter that owns its SQLite connection, exposes progress/cancel/result signals, and requires explicit confirmation before publishing a draft with excluded files.
- [x] 3.8 Add deterministic, cancellation, exclusion, staging-failure, invariant, and active-revision-preservation tests for queue construction.

## 4. Progress, Filtering, and Revision Carry-Forward

- [x] 4.1 Implement atomic-task outcome transitions for pending, completed, needs-rework, and skipped, including task selection and page-wide live-task batches.
- [x] 4.2 Commit outcome changes, reviewed signatures, timestamps, logical revision increments, and append-only outcome events in one SQLite transaction.
- [x] 4.3 Implement page-state and queue-summary derivation from task outcomes, freshness, and live-binding availability.
- [x] 4.4 Implement default actionable navigation over pending, needs-rework, and stale-completed tasks plus explicit completed, skipped, unresolved, and all-item filters.
- [x] 4.5 Implement durable cursor updates only after successful activation and nearest-next eligible resume behavior for filtered or unavailable saved pages.
- [x] 4.6 Implement in-place reconcile that refreshes paths, bindings, freshness, unavailable entries, and new-candidate counts without changing frozen membership.
- [x] 4.7 Implement explicit rebuild carry-forward for exact or confirmed task matches, with new tasks pending and unmatched prior rows retained in revision history.
- [x] 4.8 Add tests for mixed smart pages, selected-task actions, page-wide completion, stale completion, reset, filtered boundaries, resume, reconcile invariance, and conservative rebuild carry-forward.

## 5. Dataset Queue Controller and Safe Navigation

- [x] 5.1 Add a narrow image-local controller API that activates externally supplied frozen pages and suppresses automatic image-load rebuilding while dataset queue mode owns the session.
- [x] 5.2 Implement a dedicated dataset queue controller with idle, building, draft-confirmation, opening, reconciling, active, transitioning, rebuilding, persistence-blocked, and closed states.
- [x] 5.3 Implement create/open/close/save-as/backup lifecycle, writer-lease acquisition/release, heartbeat, and read-only diagnostic opening.
- [x] 5.4 Implement guarded cross-file next/previous transitions that wait for dirty-file resolution, destination load success, locator rehydration, and page activation before committing the cursor.
- [x] 5.5 Coalesce repeated navigation while transitioning and preserve the prior cursor and outcomes on cancel or destination-load failure.
- [x] 5.6 Implement save-first outcome commands and a complete-and-next command whose durable completion survives a later navigation failure.
- [x] 5.7 Enter persistence-blocked state after lease/revision/write failure, prevent further outcome mutations, and support retry, save-as, or deliberate close without claiming unsaved progress.
- [x] 5.8 Add controller tests with fake host/load/save adapters covering cross-file success, dirty save/discard/cancel, load failure, completion save failure, complete-and-next ordering, filtering, and persistence blocking.

## 6. Inspector Queue Workflow

- [x] 6.1 Extend the target-review tab with a clearly separated dataset-queue section for create, open, close, rebuild, reconcile, backup, and cancel actions.
- [x] 6.2 Add scan progress and draft-exclusion confirmation without replacing the currently active local or dataset session before successful publication.
- [x] 6.3 Add current source/page details and a maximum-three-row atomic-task list showing label/group summary, outcome, freshness, and binding state.
- [x] 6.4 Add selected-task and page-wide completed, needs-rework, skipped, pending/reset, and complete-and-next controls, disabling unsafe actions for unresolved or read-only entries.
- [x] 6.5 Add actionable/completed/needs-rework/skipped/stale/unresolved/all filters, task/page counters, progress reduction statistics, and no-actionable-work feedback.
- [x] 6.6 Add reconciliation and recovery UI for moved roots, missing/orphaned/ambiguous targets, manual binding, stale lease takeover, unsupported schema, integrity failure, and save-as fallback.
- [x] 6.7 Register all new strings through Qt translation calls, update translation sources, compile `.qm` files/resources, and keep generated resources untouched except through the compiler.
- [x] 6.8 Add offscreen widget tests for queue controls, progress, exclusions, task selection, outcome enablement, filters, summaries, warnings, recovery choices, and read-only state.

## 7. LabelWidget, Lifecycle, and Shortcut Integration

- [x] 7.1 Add narrow `LabelWidget` host methods/signals for ordered dataset descriptors, effective label-path mapping, save-current-file, guarded asynchronous load requests, and load completion/failure.
- [x] 7.2 Wire the dataset queue controller without moving database, matching, or queue algorithms into `label_widget.py`.
- [x] 7.3 Make local current-image review and dataset queue review mutually exclusive while preserving pre-session viewport capture/restore, Canvas focus ownership, selection, undo, and autosave.
- [x] 7.4 Preserve F2/Shift+F2 as next/previous eligible page across image boundaries and route optional outcome shortcuts through the existing configurable shortcut and conflict validator.
- [x] 7.5 Block navigation and outcome shortcuts during drawing, dragging, modal editing, building, transitioning, or persistence-blocked states with concise status feedback.
- [x] 7.6 Handle dataset replacement, output-directory changes, application close, sidecar move attempts, and abnormal worker/controller teardown without leaving focus predicates, leases, or transient viewport state behind.
- [x] 7.7 Add focused integration tests proving no queue ids, outcomes, page ids, locators, or persistence fields enter saved annotation JSON.

## 8. Verification and Documentation

- [x] 8.1 Run the pure virtual-review queue, locator, store, reconciliation, packing, session, and task-builder test suites with Black and flake8 on all changed Python and test files.
- [x] 8.2 Run the focused offscreen Inspector/controller/LabelWidget tests outside the sandbox if PyQt DLL loading requires it.
- [x] 8.3 Benchmark build publication, open/resume, outcome commit, cursor commit, and filtered-next lookup on representative queues, including approximately 500 files and a larger dataset-index-scale fixture.
- [x] 8.4 Exercise crash-before-commit, corrupt database, backup recovery, live second writer, stale lease, moved dataset root, deleted file, ambiguous repeated objects, and rebuild rollback scenarios.
- [x] 8.5 Document the user workflow, sidecar portability/backup rules, outcome and stale semantics, reconcile-versus-rebuild distinction, and the first-version non-goals.
- [x] 8.6 Run `openspec validate add-cross-file-virtual-review-queue --strict` and the repository's applicable pre-commit checks, then record any intentionally deferred performance or usability findings.
