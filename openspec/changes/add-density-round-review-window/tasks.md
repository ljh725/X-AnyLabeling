## 1. Deterministic partition core

- [x] 1.1 Implement the pure-Python rectangle snapshot, balanced partition, frozen boundary, pending-limit, and membership session model.
- [x] 1.2 Add unit tests for orientation ordering, balanced sizes, zero instances, frozen edits, deletion, and main/review-window creation assignment.

## 2. Canvas review adapters

- [x] 2.1 Add independent inspection render and interaction overrides to Canvas without mutating persisted shape visibility.
- [x] 2.2 Add a focused review Canvas adapter with shape-ID projection hooks, current-round visibility, read-only all-preview, and edit-lock checks.
- [x] 2.3 Add Canvas-level tests proving hidden review objects cannot be hovered, selected, boxed, or edited while temporary all-preview remains read-only.

## 3. Review window and controls

- [x] 3.1 Build the top-level single-round review window with a large scrollable canvas and no copied main-window panels.
- [x] 3.2 Build the compact review bar for filename, last-closed filename, previous/next/direct round navigation, progress, and current/pending limits.
- [x] 3.3 Add window geometry restore/fallback, fit-on-image-change, stable viewport-on-round-change, and close lifecycle behavior.

## 4. Shared editing coordinator

- [x] 4.1 Implement main-document-to-review projection synchronization keyed by persistent shape ID.
- [x] 4.2 Implement review-to-main live geometry/metadata transactions, per-object locks, one main-owned undo snapshot, dirty state, and repaint synchronization.
- [x] 4.3 Route review create/copy/delete/relabel and shared label-dialog operations through existing LabelingWidget business paths.
- [x] 4.4 Rebuild projections after main create/delete/relabel/undo while preserving frozen session membership rules.

## 5. Selection, visibility, and navigation integration

- [x] 5.1 Implement immediate review-to-main selection synchronization and main-window pending-selection status.
- [x] 5.2 Implement confirmed `Ctrl+J` main-to-review synchronization, same-round multi-select validation, and pending-selection conflict clearing.
- [x] 5.3 Suspend and restore category filters, per-object hiding, and conflicting isolation/review modes while keeping the main window globally visible.
- [x] 5.4 Integrate ordered/direct round navigation with selection clearing, save-guarded cross-image navigation, first/last dataset bounds, and zero-instance images.

## 6. Configuration, shortcuts, and localization

- [x] 6.1 Add default/pending round-limit configuration and configurable `F10`, `[`, `]`, `Ctrl+J`, and hold-`V` actions with guarded focus behavior.
- [x] 6.2 Persist only review-window geometry and last-closed image name, never enabled state, round completion, or JSON metadata.
- [x] 6.3 Add translated user-facing strings, update translation sources, and rebuild generated Qt language resources with the repository script.

## 7. Verification

- [x] 7.1 Add PyQt offscreen tests for dual-window editing, live synchronization, shared undo, edit locks, selection asymmetry, and viewport behavior.
- [x] 7.2 Add integration tests for visibility restoration, delayed limit application, cross-image save failure, navigation shortcuts, and lifecycle persistence.
- [x] 7.3 Run focused tests, Black on touched hand-written Python, Flake8 on touched modules/tests, and OpenSpec strict validation; document any pre-existing unrelated failures.

### Verification notes

- Focused suite: 22 passed, including the pure partition tests, PyQt dual-window tests, configuration tests, a real `LabelingWidget` construction regression test, and an end-to-end F10 window activation test.
- Black and `py_compile` passed for all hand-written Python touched by this change. The repository targets Python 3.15 syntax while the configured test interpreter is Python 3.12, so Black emitted its existing target-version safety warning after formatting successfully.
- Flake8 passed for the two new implementation modules and their tests. The two pre-existing high-cost host files still report 8 unrelated findings outside this change's edited regions: 7 `F841` signal-blocker variables and the existing `C901` complexity of `LabelingWidget.update_attributes`.
- All four Qt translation catalogs and the generated resource module were rebuilt successfully.
- `openspec validate add-density-round-review-window --strict` passed.

## 8. Post-validation usability adjustments

- [x] 8.1 Force masks off in the review Canvas and synchronize all other supported information-display and appearance settings from the main Canvas.
- [x] 8.2 Reuse the existing digit rename mappings for selected review rectangles, including shared undo/redo and input-focus guards.
- [x] 8.3 Add regression tests for live display synchronization, permanent mask suppression, digit relabeling, and shared history; rerun focused quality gates.

### Post-validation verification notes

- Focused suite: 31 passed, including live main-to-review display synchronization, permanent review-mask suppression, review-window digit relabeling, and shared undo/redo.
- Black and `py_compile` passed for all hand-written Python touched by the adjustment. Focused Flake8 passed for the review coordinator, digit rename manager, and regression tests.
- The pre-existing `C901` complexity finding in `SettingsRuntimeApplier.apply_change` remains outside this adjustment's edited logic.
- `openspec validate add-density-round-review-window --strict` passed after the specification, design, and task updates.
