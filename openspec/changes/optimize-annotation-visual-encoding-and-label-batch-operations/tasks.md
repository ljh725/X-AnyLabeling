## 1. Baseline and Module Boundaries

- [x] 1.1 Add focused regression tests that demonstrate color-only label edits currently enter the JSON rewrite path and cancel currently leaks draft color state
- [x] 1.2 Add focused regression tests for the current LabelWidget/Canvas `group_id` color mismatch, including `group_id=0`
- [x] 1.3 Create the pure-Python `widgets/appearance/` package skeleton and keep it free of PyQt imports
- [x] 1.4 Define typed immutable appearance settings, color-mode, visual-context and visual-style models
- [x] 1.5 Define typed immutable label-change draft, plan, preflight summary and operation-result models

## 2. Safe Label Change Planning

- [x] 2.1 Implement isolated label metadata drafts so dialog edits do not mutate parent state before confirmation
- [x] 2.2 Implement plan diffing that separates color/visibility changes from rename/delete dataset mutations and detects no-op confirmation
- [x] 2.3 Implement explicit rename-to-existing-label merge detection and confirmation data
- [x] 2.4 Implement dirty-current-file preflight outcomes for save, discard and cancel without starting a worker prematurely
- [x] 2.5 Add pure-Python tests for draft cancellation, no-op plans, visual-only plans, rename/delete plans and merge conflicts

## 3. Candidate Discovery and JSON Transformation

- [x] 3.1 Add a read-only candidate provider contract for querying annotation files by target labels
- [x] 3.2 Implement dataset-index-backed candidate selection with stale/unavailable detection
- [x] 3.3 Implement cancellable background scan fallback when no trustworthy index is available
- [x] 3.4 Implement a pure JSON transformation that renames/deletes target labels while preserving unrelated top-level, shape and unknown extension fields
- [x] 3.5 Skip candidate files whose verified content has no target match or whose transformed content is unchanged
- [x] 3.6 Add tests for sparse hits in large candidate sets, stale index fallback, unknown-field preservation and no-op file timestamps

## 4. Transactional Batch Migration

- [x] 4.1 Define a versioned transaction manifest with source path, backup path, staged path, original fingerprint and per-file result
- [x] 4.2 Implement same-volume staging and re-parse validation before any source file is replaced
- [x] 4.3 Implement per-file atomic replacement and preserve recoverable backups for every committed file
- [x] 4.4 Make preflight and staging cancellable while making the commit phase explicitly non-cancellable
- [x] 4.5 Implement partial-failure result accounting for succeeded, failed, skipped and cancelled files
- [x] 4.6 Implement manifest-driven restore with atomic replacement and verification
- [x] 4.7 Add a dataset write coordinator that prevents batch commit from racing autosave or another migration
- [x] 4.8 Add tests for validation failure, permission/replacement failure, cancellation boundaries, partial commit and successful restore

## 5. Label Manager Worker and UI Integration

- [x] 5.1 Add a QThread worker adapter that runs candidate discovery, staging and commit without touching Qt widgets
- [x] 5.2 Emit bounded progress updates with phase, processed count and candidate total, plus one terminal structured result
- [x] 5.3 Replace direct `parent.label_info` mutation in the dialog with the isolated draft and restore true cancel semantics
- [x] 5.4 Route color/visibility-only confirmation to project visual metadata and a single batched current-canvas refresh with zero annotation JSON I/O
- [x] 5.5 Add destructive delete preflight showing affected file and shape counts
- [x] 5.6 Add rename merge confirmation, dirty-file resolution and clear commit-stage cancellation messaging
- [x] 5.7 Replace the synchronous `modify_label()` loop with the worker lifecycle and disable only conflicting dataset actions
- [x] 5.8 Show accurate success/partial failure/cancel summaries and expose restore information for retained transactions
- [x] 5.9 Resynchronize the current file, label summary and affected dataset-index paths from actual disk results
- [ ] 5.10 Add PyQt offscreen tests for responsiveness, progress, cancel, color-only zero-I/O, one repaint and partial-result UI

## 6. Appearance Configuration and Palette

- [x] 6.1 Add `annotation_appearance` defaults and schema validation for mode, outline, opacity, label/GID display and unrelated-object opacity
- [x] 6.2 Implement a deterministic accessible base palette that never returns the reserved background entry for a valid label/group/instance
- [x] 6.3 Implement consistent `focus`, `label`, `group`, `instance` and `uniform` base-color resolution
- [x] 6.4 Add project appearance sidecar loading/saving with schema versioning, root resolution and read-only fallback warnings
- [x] 6.5 Migrate legacy `shape_color`, `label_colors`, default color and auto-shift values in memory with documented precedence
- [x] 6.6 Add Settings/Appearance controls with immediate live apply and persist only user-owned display preferences globally
- [x] 6.7 Add tests for all modes, palette cycling, `group_id` boundary values, sidecar persistence and legacy migration

## 7. High-Contrast Rendering Integration

- [x] 7.1 Add a Qt adapter that converts immutable visual styles into pens, brushes, text badges and opacity without mutating Shape data
- [x] 7.2 Extend the compatible Shape/Canvas paint path to accept resolved render context while retaining a temporary legacy fallback
- [x] 7.3 Draw rectangle outer contrast stroke and inner semantic stroke at stable screen-pixel widths
- [x] 7.4 Apply independent normal, hover and selected fill opacity with normal fill disabled by default
- [x] 7.5 Add optional label and GID badges with collision-tolerant identity text and viewport-aware placement
- [ ] 7.6 Enforce render precedence so selection, control points, active-edge feedback and QA markers remain distinguishable in every color mode
- [x] 7.7 Replace duplicate LabelWidget/Canvas group-color formulas with the shared resolver and remove the `group_id=0` black mismatch
- [x] 7.8 Cache stable base styles and confirm viewport culling prevents the two-stroke path from regressing dense-scene paint performance
- [ ] 7.9 Add offscreen screenshot or pixel tests across light/dark backgrounds, multiple zoom levels and combined interaction states

## 8. Group Focus Visualization

- [x] 8.1 Implement the pure focus state machine for valid group selection, same-group multi-select, mixed selection and ungrouped values
- [x] 8.2 Connect normalized selection snapshots to focus transitions without reusing the rectangle-refine focus state container
- [x] 8.3 Apply focused-group emphasis and unrelated-object neutral dimming only after existing visibility gates pass
- [x] 8.4 Clear stale focus on blank click, selection clear, mixed selection, mode change, deletion, image unload and image switch
- [x] 8.5 Preserve virtual-review context opacity and filter/label visibility while focus mode is active
- [x] 8.6 Add explicit quick switching between Focus, Label, Group, Instance and Uniform views without changing dirty or undo state
- [x] 8.7 Add tests for ten-group density, person/head/face synchronization, hidden same-group objects, virtual review and cross-image cleanup

## 9. Performance, Recovery, and Acceptance

- [ ] 9.1 Add a 10k-JSON sparse-hit benchmark that records candidate count, files read, files written, cancellation latency and GUI-thread file I/O violations
- [ ] 9.2 Add a dense-current-image benchmark proving a class color change produces one merged repaint rather than per-shape refreshes
- [ ] 9.3 Run an artificial light/dark/texture image matrix to compare legacy single-stroke rendering with the new high-contrast style
- [ ] 9.4 Run a ten-group person/head/face human review trial comparing Focus and Group modes and record visual confusion feedback
- [x] 9.5 Verify appearance/focus actions never enter JSON, dirty, undo, autosave, quality feedback or export outputs
- [ ] 9.6 Verify transaction directories, disk-space preflight, cleanup policy and restore instructions on Windows paths and separate output directories

## 10. Documentation, Localization, and Quality Gates

- [ ] 10.1 Add translated UI strings for Appearance modes, opacity controls, progress phases, destructive confirmations and recovery results
- [x] 10.2 Update user-facing documentation for the five color modes, Focus behavior, project palette location and batch-operation safety model
- [x] 10.3 Run `scripts/compile_languages.py` and verify generated translation resources without manual edits
- [x] 10.4 Run the focused appearance, focus, label-manager, dataset-index, rectangle-edge and virtual-review test files with Qt offscreen
- [ ] 10.5 Run Black on changed Python files with a writable cache and run flake8 on changed modules/tests
- [x] 10.6 Perform final OpenSpec strict validation and a manual rollback check with the new appearance feature disabled
