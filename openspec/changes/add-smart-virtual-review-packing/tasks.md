## 1. Packing data model and validation

- [x] 1.1 Add pure-Python packing mode, immutable option, page, and result types under `virtual_review`, including exported public symbols.
- [x] 1.2 Define single, balanced, and high-density preset option values, with balanced defaulting to at most two tasks and high-density to at most three tasks per page.
- [x] 1.3 Validate viewport dimensions, page limits, fit margin, projected anchor-size threshold, and projected gap threshold; reject non-finite, negative, or unsupported values.
- [x] 1.4 Preserve atomic task ids, ordered task ids, union member ids, anchor ids, union bbox, and packing diagnostics in immutable page/result objects without adding serialized Shape fields.

## 2. Geometry evaluation and deterministic packer

- [x] 2.1 Implement pure bbox union, overlap, image-space gap, padded fit-scale, projected anchor short-side, and projected pairwise-gap helpers.
- [x] 2.2 Implement tentative-page evaluation that checks every anchor-size and pairwise-gap hard gate against explicit packing options.
- [x] 2.3 Implement single-task mode as deterministic singleton-page wrapping of the existing ordered `VirtualTask` list.
- [x] 2.4 Implement deterministic seed-and-grow packing for balanced and high-density modes, using worst projected anchor size, normalized union area, and original task order for stable candidate ranking.
- [x] 2.5 Guarantee coverage invariants: never split an atomic task, never duplicate or omit a task, never exceed the page limit, and preserve a stable page order.
- [x] 2.6 Fail closed for missing/invalid geometry or viewport data by emitting affected tasks as singleton pages and reporting fallback counts in the packing result.

## 3. Page session and controller integration

- [x] 3.1 Upgrade the frozen review session to navigate uniform page items in every display mode while retaining boundary messages and safe missing-anchor handling.
- [x] 3.2 Adapt `VirtualReviewController` generation to build atomic tasks first, capture the current viewport size, validate packing options, and then build frozen pages.
- [x] 3.3 Activate a page by installing the union of all surviving page member runtime ids into the existing Canvas virtual-focus predicate.
- [x] 3.4 Select the first surviving page anchor deterministically and fit/center the viewport on the surviving page union bbox with the existing margin behavior.
- [x] 3.5 Skip a page only when none of its task anchors survives; retain surviving tasks and members when part of a page is deleted during the frozen session.
- [x] 3.6 Preserve the current generated page list through label, group-id, and geometry edits; rebuild only on explicit regeneration or successful image load.
- [x] 3.7 Preserve first-stage drawing/drag/modal navigation guards, pre-session viewport restoration, image-change viewport protection, and conflicting focus-mode clearing.

## 4. Inspector packing controls and feedback

- [x] 4.1 Add display-mode controls for single-task, balanced, and high-density packing to the Inspector target-review tab.
- [x] 4.2 Add visible editable controls for maximum tasks per page, minimum projected anchor pixels, and minimum projected gap pixels.
- [x] 4.3 Apply named preset values to the explicit controls without hiding the effective values, and make single-task mode force a one-task page limit.
- [x] 4.4 Validate criteria and packing inputs before emitting generation; invalid input must leave the existing active session and page unchanged.
- [x] 4.5 Update progress feedback to show current page/total pages, current-page atomic task count, total atomic tasks, singleton fallback count, and task-to-page reduction.
- [x] 4.6 Keep “查看全图”, regenerate, exit, F2 next, and Shift+F2 previous behavior compatible with the first-stage controls.
- [x] 4.7 Add English, Simplified Chinese, Japanese, and Korean strings for packing controls/statistics, then regenerate `.qm` files and Qt resources through `scripts/compile_languages.py`.

## 5. Compatibility and persistence boundaries

- [x] 5.1 Verify that all current-page tasks are normally rendered and interactive while base-visible non-page shapes remain dim and non-interactive without mutating base filter visibility.
- [x] 5.2 Preserve the existing `F1` digit-page action and runtime shortcut settings while F2 / Shift+F2 navigate packed pages directly without a full-image intermediate state.
- [x] 5.3 Keep page ids, task membership, packing options, scores, and diagnostics out of Shape serialization and annotation JSON.
- [x] 5.4 Preserve existing undo, autosave, manual save, unsaved-image-change protection, and current-image-only lifecycle behavior for edits made on multi-task pages.
- [x] 5.5 Do not add physical split files, cross-file page membership, persistent review progress, automatic annotation edits, or model-driven pairing in this stage.

## 6. Tests and verification

- [x] 6.1 Add pure unit tests for bbox gaps, overlaps, fit scale, projected screen size, projected screen gap, invalid viewport data, and numeric option validation.
- [x] 6.2 Add pure packer tests for singleton mode, compatible combinations, too-small rejection, too-close rejection, page limits, deterministic tie-breaking, and invalid-geometry fallback.
- [x] 6.3 Add invariant/property-style cases proving every task appears exactly once, group tasks remain indivisible, page order is stable, and 25–30-task inputs complete without pathological behavior.
- [x] 6.4 Add session tests for page boundaries, frozen membership, surviving partial pages, fully deleted-page skipping, and explicit rebuild behavior.
- [x] 6.5 Add offscreen Inspector tests for preset application, editable effective thresholds, invalid-input session preservation, and packing summary/progress text.
- [x] 6.6 Add offscreen controller/Canvas tests for multi-task focus membership, non-page interaction rejection, first surviving anchor selection, union-bbox viewport fitting, and no full-image navigation intermediate.
- [x] 6.7 Add regression tests for F1/F2 compatibility, viewport restoration, image-load rebuild, undo runtime identity, base-filter preservation, and annotation serialization boundaries.
- [x] 6.8 Run focused pure and PyQt test suites, flake8 on changed/new modules and tests, Python compilation checks, translation compilation, `git diff --check`, and strict OpenSpec validation.
