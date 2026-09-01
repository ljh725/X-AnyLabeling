# Verification

Date: 2026-09-01

## Automated regression

- Command: `python -m pytest tests/test_annotation_clipboard_paste.py tests/test_canvas_change_notifications.py tests/test_rectangle_size_monitor.py tests/test_rectangle_size_controller.py tests/test_shape_identity.py -q`
- Environment: project `x-anylabeling-cu12` interpreter with `QT_QPA_PLATFORM=offscreen`.
- Result: **58 passed in 12.70s**.
- Coverage includes repeated in-memory and system-clipboard paste, multi-shape batches, three-image navigation, append atomicity, replacement compatibility, monitor identity assertions, undo, real JSON/PNG save and reload, and rectangle-size overlay synchronization.

## Quality gates

- Black line length 79 completed on all touched Python areas with a writable `BLACK_CACHE_DIR`.
- Strict Flake8 passed for `canvas.py`, `rectangle_size_monitor.py`, `test_annotation_clipboard_paste.py`, and `test_rectangle_size_monitor.py`.
- Scoped Flake8 passed for `label_widget.py` while ignoring its unrelated pre-existing `F841`, `C901`, and `F541` findings in the dirty worktree.
- `py_compile` passed for all touched implementation and test files.
- `git diff --check` reported no whitespace errors.

## Operational smoke

The offscreen Qt smoke sequence performed one paced paste followed by two immediate pastes on the same image, processed the resulting overlay updates, undid the last paste, saved to a real LabelMe-style JSON plus PNG, reloaded the file, and verified annotation counts, live-object uniqueness, persistent-ID uniqueness, and rectangle-size overlays. A separate sequence retained the copy templates while replacing the Canvas snapshot across three simulated images and pasted a fresh object on every target.

## Compatibility statement

This change introduces no annotation-format, configuration, dependency, database, or migration changes. Existing system-clipboard deserialization remains supported. The only new runtime contract is rejecting aliased live `Shape` references atomically before Canvas or label-list mutation.
