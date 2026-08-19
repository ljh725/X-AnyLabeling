## 1. Pure task model and builder

- [x] 1.1 Add the `virtual_review` pure-Python package with criteria, task, runtime-identity, and session data types.
- [x] 1.2 Implement deterministic anchor matching for label, shape type, group-id mode/value, and inclusive pixel width/height ranges.
- [x] 1.3 Implement group expansion/deduplication and ungrouped single-shape fallback without writing task metadata to JSON.
- [x] 1.4 Implement frozen previous/next session navigation, boundary messages, and safe handling of deleted members/anchors.

## 2. Core tests

- [x] 2.1 Add unit tests for criteria matching, size boundaries, group expansion, deduplication, and deterministic order.
- [x] 2.2 Add unit tests for session navigation, frozen membership, boundaries, and deleted-shape handling.

## 3. Canvas and viewport integration

- [x] 3.1 Add a transient virtual-task focus predicate that composes with base visibility without mutating existing filter state.
- [x] 3.2 Render unrelated base-visible shapes as dim context and reject their normal hover/selection/edit interaction while a task is active.
- [x] 3.3 Add a Qt controller that applies task focus, selects the anchor, centers/zooms the union bbox, and restores the pre-session viewport.
- [x] 3.4 Guard virtual navigation during drawing, dragging, and modal editing; clear conflicting three-box/Pose click focus when the session starts.

## 4. Inspector UI

- [x] 4.1 Add the Inspector “目标复核” tab with label/shape/group-id/width/height criteria controls and validation messages.
- [x] 4.2 Add generate/rebuild/exit/overview controls and current-task progress display.
- [x] 4.3 Connect Inspector signals to the controller and rebuild tasks after successful image loads while the mode is active.

## 5. Shortcuts and settings

- [x] 5.1 Register `virtual_review_next: F2` and `virtual_review_prev: Shift+F2` in default config and settings schema.
- [x] 5.2 Wire runtime shortcut application and LabelWidget actions while preserving the existing F1 digit-page action.
- [x] 5.3 Add translated UI strings and regenerate Qt resources.

## 6. Integration tests and verification

- [x] 6.1 Add offscreen tests for focused rendering/interaction, navigation without full-image intermediate state, and viewport restoration.
- [x] 6.2 Add integration tests for F1 compatibility, F2/Shift+F2 navigation, image-change save protection, undo identity, and base-filter preservation.
- [x] 6.3 Run targeted tests, compile changed Python modules, and validate the OpenSpec change.
