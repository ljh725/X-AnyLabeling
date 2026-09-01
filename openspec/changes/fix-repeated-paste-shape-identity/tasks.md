## 1. Regression Tests for Paste Semantics

- [x] 1.1 Add a focused offscreen Qt regression test that uses the in-memory clipboard, copies one Shape once, invokes paste twice sequentially on one image, and demonstrates the current duplicate-object failure before the fix.
- [x] 1.2 Extend the regression test to require two newly pasted live objects, distinct `xanylabeling_shape_id` values, independent edit behavior, exact annotation counts, and no duplicate-object exception with `RectangleSizeMonitor` connected.
- [x] 1.3 Add multi-selection repeated-paste coverage that verifies every invocation creates a complete independent batch while preserving copied labels, geometry, attributes, descriptions, and within-batch grouping metadata.
- [x] 1.4 Add navigation coverage for copy → paste → change image → paste, verifying clipboard persistence and fresh live and persistent identities on each target image.
- [x] 1.5 Add compatibility coverage for system-clipboard paste and verify label-list entries and Canvas entries reference the same newly created Shape for each valid paste.

## 2. Fresh Paste Materialization

- [x] 2.1 Refactor the non-system-clipboard branch of `paste_selected_shape()` so `_copied_shapes` remains a reusable template collection and every invocation materializes a new list with `Shape.copy_for_new_object()`.
- [x] 2.2 Derive `created_count`, dirty-state changes, selection/filter refresh behavior, and behavior-analytics events from the materialized batch so rapid repeated paste records exactly the annotations actually created.
- [x] 2.3 Verify pasted objects do not retain inappropriate transient selection, hover, or filter-only state while preserving the existing annotation field and `group_id` copy contract.

## 3. Atomic Live-Object Identity Preflight

- [x] 3.1 Introduce one reusable identity-preflight implementation that materializes an incoming iterable once, rejects duplicate object references within it, and for append operations rejects objects already owned by the current Canvas without conflating object identity with persistent shape ID.
- [x] 3.2 Invoke the shared preflight in `LabelingWidget.load_shapes()` before label-list mutation and in `Canvas.load_shapes()` before overlay reset, identity normalization, backup changes, selection changes, or `self.shapes` mutation.
- [x] 3.3 Preserve replacement workflows by allowing `replace=True` to reuse objects from the previous Canvas snapshot while still rejecting duplicate references within the replacement snapshot.
- [x] 3.4 Add atomicity tests proving invalid append requests leave Canvas membership/order, label-list contents, selection, backups, dirty state, behavior-event counts, and emitted full-shape snapshots unchanged.
- [x] 3.5 Retain the duplicate-object assertion in `RectangleSizeMonitor.replace_shapes()` and verify valid repeated paste reaches the monitor with a unique-reference snapshot rather than catching or suppressing its exception.

## 4. Verification and Quality Gates

- [x] 4.1 Run the new focused paste tests together with `tests/test_canvas_change_notifications.py`, `tests/test_rectangle_size_monitor.py`, `tests/test_rectangle_size_controller.py`, and `tests/test_shape_identity.py` using the project conda interpreter and Qt offscreen mode.
- [x] 4.2 Run Black with line length 79 and a writable `BLACK_CACHE_DIR` on touched Python files, then run scoped Flake8 and `py_compile` checks on the implementation and new test files.
- [x] 4.3 Perform a manual smoke check for slow and rapid repeated paste on one image, cross-image paste across at least three images, undo after repeated paste, save/reload, and rectangle-size overlays; confirm no annotation is dropped or aliased.
- [x] 4.4 Record final verification results and confirm the change introduces no annotation-format, configuration, dependency, or migration changes.




