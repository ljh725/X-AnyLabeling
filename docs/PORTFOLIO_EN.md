# Portfolio · X-AnyLabeling Extended Features

> A personal practice of extending [CVHub520/X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) beta.4 — an AI-powered image/video annotation desktop app.
>
> English | [简体中文](PORTFOLIO.md)

---

## Fork Relationship

This repo is my ([@ljh725](https://github.com/ljh725)) personal fork of `CVHub520/X-AnyLabeling`.
**All features listed below are extensions I independently designed and implemented on top of beta.4** — upstream features are not included in this portfolio.

```
CVHub520/X-AnyLabeling (upstream, beta.4)
        │  fork
        ▼
ljh725/X-AnyLabeling  ← this repo (93 commits / ~15k LOC of extensions)
```

| Metric | Value |
|--------|-------|
| Commits | **93** (vs upstream main) |
| New code | **~18,500 lines** (features + tests) |
| Test cases | **300+** (feature-related) |
| Design docs | **116** (in `docs/`) |
| Feature modules | **15** |

---

## Feature Matrix

| # | Module | LOC | Tests | Core value | Details |
|---|--------|-----|-------|-----------|---------|
| 1 | **L1/L2 Quality Engine** | 4,354 / 12 files | 148 | 12 geometry/visual-relationship rules + face→head→person cross-class matching, pure Python (zero PyQt), CLI/UI share one logic core | [→ 01](portfolio/01-quality-engine.md) |
| 2 | **Inspector Panel** | 3,785 / 10 files | 60+ | 5-tab QA workbench, plug-in rule engine, click-to-navigate, in-app quality loop | [→ 02](portfolio/02-inspector-panel.md) |
| 3 | **Selection Optimization** | ~90 core | 6 | "Decision-to-Sort" pattern: 4-tuple priority ranking replaces if-elif chains, solves mis-selection in dense/nested annotations | [→ 03](portfolio/03-selection-optimization.md) |
| 4 | **Rect Edge Editing** | 407 geometry + ~250 canvas | 21 | Drag a single rectangle edge independently, geometry/UI decoupling, anti-flip clamp | [→ 04](portfolio/04-rect-edge-edit.md) |
| 5 | **Pose View Decoupling** | 1,994 / 9 files | 36 | filter-driven single-field decoupling of label list vs focus, 4 occlusion-free layout algorithms, overview/selected two-state display | [→ 05](portfolio/05-pose-view.md) |
| 6 | **Data Toolkit** | 40 scripts (3,000+ core) | — | YOLO-Pose 3-step pipeline + ViTPose pre-label diff + QC CLI, full pose-data-production chain | [→ 06](portfolio/06-data-toolkit.md) |
| 7 | **Auto Person Instance** | ~60 core + settings/integration | 9 | Auto-mint group_id on manual person-rectangle draw; priority chain `bind_draw > this > auto_use_last_gid`; static Non-Goal test | [→ 07](portfolio/07-auto-person-instance.md) |
| 8 | **Digit Bind Draw** | 414-line manager + integration | 19 | Select source, press digit to draw same-instance box; lazy backfill for undo atomicity; two-stage TOCTOU duplicate guard | [→ 08](portfolio/08-digit-bind-draw.md) |
| 9 | **Precision Refinement** | ~250 canvas + settings | 14 | zoom/fixed drag slowdown + Tab edge-select + 1px/5px single-edge nudge; virtual-cursor isolation zero-pollutes base interactions | [→ 09](portfolio/09-precision-mode.md) |
| 10 | **Local Edge Snap (experimental)** | 212 pure Python + canvas bridge | 11 | Sobel-gradient ±4px search + dual threshold, pure-algorithm unit-testable; honestly records "directional bias" and self-deprio'd | [→ 10](portfolio/10-local-edge-snap.md) |
| 11 | **Filter System** | ~1,400 / 5 files | — | Filter persistence across image switches + JSON engine + SQLite index cache (5k-image speedup) + cross-file navigation; State/Engine/UI layering | [→ 11](portfolio/11-filter-system.md) |
| 12 | **Zoom Center Fix** | ~70 core + 2 analysis docs | — | Fixes upstream portrait-image zoom drift (width-detection no-ops + y misuses width ratio); rewritten with transform_pos inverse | [→ 12](portfolio/12-zoom-center-fix.md) |
| 13 | **Digit Shortcut Pagination** | 311-line page manager | — | Extends upstream's 10-key limit: F1 page-switch, 10×N slots, single-page is fully backward-compatible | [→ 13](portfolio/13-digit-shortcut-pagination.md) |
| 14 | **Digit Shortcut Rename** | 400-line manager + dialog | — | Select shapes, press digit to batch-relabel (no upstream equivalent); independent config + full side-effect chain | [→ 14](portfolio/14-digit-rename.md) |
| 15 | **Viewport Persistence** | 359-line controller | — | Keep zoom + view center across image switches; image-coordinate persistence survives size changes, reuses module 12's coordinate model | [→ 15](portfolio/15-viewport-persistence.md) |

---

## Module Cards

### 1. L1/L2 Quality Engine

**Problem**: Pose-annotation datasets are large; manually checking the geometric relationships among face/head/person boxes (is the face inside the head? is the head at the top of the person? are keypoints out of bounds?) is prohibitively expensive, and rules are hard to reuse.

**Solution**: A pure-Python two-tier quality engine — L1 checks JSON structural validity, L2 evaluates cross-class relationships via 12 geometry/visual rules, paired with a face→head→person cross-class matching algorithm (hard filter + weighted scoring) and a threshold-evaluation system.

**Highlights**:
- 🏗️ **Strict pure-Python / PyQt layering**: 12 files in `quality/` with **zero PyQt imports** — runs headless in CI, CLI and UI share one logic core
- 🎯 **12 L2 rules**: L2-01 face matches head, L2-03 face/head area ratio, L2-06 head/person spatial position, L2-09 keypoint overflow, L2-12 image-level density anomaly...
- 🔗 **Cross-class matching**: face→head (strict, 5 hard filters + 4-dim scoring) / head→person (loose, 4 hard filters + 5-dim scoring), triangular peak decay for smooth scoring
- ⚖️ **Threshold evaluation**: 4 directions + `error_requires` secondary-confirmation downgrade (error hits but confirmation fails → auto-downgrade to warning)
- 💡 **Threshold suggestion**: 9-level priority trigger table, produces non-binding suggestions from human-review stats (always pending, never auto-edits config)

📊 Stats: 4,354 lines · 148 test cases · [Details](portfolio/01-quality-engine.md)

---

### 2. Inspector Panel

**Problem**: The original workflow was "annotate → export JSON → external Python script check → manually locate problem files → open & fix one by one → re-export → re-check". The QC loop lived in external scripts; discovered issues couldn't jump back to the annotation position for fixing.

**Solution**: A 5-tab QDockWidget workbench (Data Check / Quality Review / Data Table / Rule Config / Export) that brings external-script capabilities in-app — click an issue to jump straight to the shape on Canvas.

**Highlights**:
- 🧩 **Plug-in rule engine**: `ValidationRule` ABC + `check`/`check_all` dual-level, zero-intrusion to add rules
- 📋 **8 built-in rules**: label allowlist, group_id uniqueness, person-requires-gid, label-shape binding, keypoint integrity...
- 🔁 **Signal-contract reuse**: the Quality Review tab reuses the existing `issue_navigate_requested` path — **parent LabelingWidget needs zero changes**
- 🗂️ **3-dim in-memory index**: `FlatIndex`'s `_by_file/_by_label/_by_group` supports 500–1000 files/batch scanning

📊 Stats: 3,785 lines · 60+ test cases · [Details](portfolio/02-inspector-panel.md)

---

### 3. Selection Optimization

**Problem**: In dense/nested annotations (overlapping boxes, keypoints on top of rectangles, large background box containing small targets), the old `reversed + first-hit` strategy only selects "the last-created object that contains the point" — frequently mis-selecting or failing to reach the intended object.

**Solution**: The "Decision-to-Sort" pattern — compute a 4-tuple priority for each candidate shape, sort lexicographically, and let "grab vertex > grab edge > grab small object > grab top-of-stack" emerge naturally from the sort.

**Highlights**:
- 🎯 **4-tuple priority**: `(level, distance/area, area, -stack_index)`, zero if-branches
- 🧠 **Area as "specificity" proxy**: nested small objects sort first because they're smaller
- 🔁 **Three-entry reuse**: hover highlight, click-select, double-click-edit all consume the sorted first candidate
- 🧪 **Pure-algorithm unit-testable**: 6 scenarios verified without PyQt

📊 Stats: ~90 lines core algorithm · 6 scenario tests · [Details](portfolio/03-selection-optimization.md)

---

### 4. Rect Edge Editing

**Problem**: Refining a single rectangle edge (snapping to an image boundary, aligning with an adjacent box) is hard — native editing only drags corner vertices, which simultaneously moves two edges and breaks alignment on the other axis.

**Solution**: Independently select and drag any one of a rectangle's four edges (left/right/top/bottom), keeping the other three unchanged. Geometry and Canvas UI are strictly decoupled.

**Highlights**:
- 📐 **Geometry/UI decoupling**: `RectEdgeRef` is a transient edit handle holding a live `Shape` reference, but **never written back to JSON or `Shape.other_data`**
- 🛡️ **Anti-flip clamp**: `geometry_with_edge_coord` guarantees `min < max` — rectangles never collapse or flip when dragged past the opposite edge
- 🔄 **Canvas state machine**: hover → press-to-select → live coord update → release-to-commit (one release = one undo granularity) → Esc-to-cancel-restore
- 🔒 **Bidirectional draw-mode mutex**: entering create mode auto-disables edge editing and vice versa
- 📝 **Honest evolution**: this feature went through "edge alignment (snap to reference edge) → simplified to edge editing"; docs record this faithfully

📊 Stats: 407-line geometry module + ~250 lines canvas · 21 test cases · [Details](portfolio/04-rect-edge-edit.md)

---

### 5. Pose View Decoupling

**Problem**: Enabling Pose View made the renderer take over the entire image, hiding ordinary rectangle/polygon labels (a strong "split feeling"); and selecting a person polluted the selection state of the normal-label flow.

**Solution**: A filter-driven architecture — a single field `pose_focus_group_id` decouples the label list from selection focus; filtering is by shape type (not by mode toggle), letting Pose View coexist with native labels.

**Highlights**:
- 🎛️ **Filter-driven single-field decoupling**: `pose_focus_group_id` drives overview/selected two-state switching without polluting the native selection flow
- 📐 **4 occlusion-free layouts**: direct / anti (priority-sorted overlap removal) / column (quadrant vertical stacking) / category (by body part)
- 👁️ **Overview/selected two-state**: overview shows person color-coding for the big picture; selected shows skeleton+labels+leaders for detail
- 🧱 **Pure-module-first principle**: `pose_constants`/`pose_config`/`pose_layout` have zero QWidget dependencies, unit-testable standalone
- 🔧 **Event-source disambiguation**: Keypoint Fill mode's programmatic empty-selection is guarded by `is_active` to avoid clearing focus

📊 Stats: 1,994 lines / 9 files · 36 test cases · [Details](portfolio/05-pose-view.md)

---

### 6. Data Toolkit

**Problem**: Pose-data production is a full pipeline (annotation → format conversion → dataset split → visual verification → model pre-label diff → rule-based QC); each step needs a dedicated tool, and scattered scripts are hard to maintain.

**Solution**: 40 unified `argparse`-style CLI scripts covering the entire pose-data-production chain, deeply integrated with spec docs and the Inspector queue.

**Featured scripts**:
- 🔄 **YOLO-Pose 3-step pipeline**: `step1-convert_json_to_yolopose.py` (604 lines) → `step2-split_yolov8pose_dataset.py` → `step3-visualize_yolo_dataset.py`
- 🤖 **ViTPose pre-label diff**: inject predicted keypoints by group_id, use model predictions to surface human-annotation blind spots
- ✅ **QC CLI**: `run_l1l2_qc.py` (outputs review.tsv + report.json), `gen_threshold_suggestion.py`
- 📊 **Dataset stats/diff**: unique-label extraction, stem comparison, shape statistics

📊 Stats: 40 scripts (3,000+ core lines) · [Details](portfolio/06-data-toolkit.md)

---

> **Modules 7–10** revolve around one theme — "manual annotation refinement" — across two directions: **person-instance binding** (7, 8) auto-generates/inherits/backfills `group_id`, and **box refinement** (9, 10) reduces 1–3px error. Design notes unified in [docs/feature_summary.md](feature_summary.md).

### 7. Auto Create Person Instance

**Problem**: Manually typing a `group_id` for every `person` box is pure-mechanical, error-prone, low-value work (skipped/duplicate/wrong IDs).

**Solution**: On committing a manually drawn `person` rectangle, auto-call `gen_new_group_id()` (max+1) and flash "已创建 person #n" in the status bar.

**Highlights**:
- 🔗 **Priority chain**: `bind_draw > auto_person_instance > auto_use_last_gid > manual`, guarded by `if bound is None` — structurally impossible to conflict with bind_draw
- ♾️ **Orthogonal coexistence**: not mutually exclusive with `auto_use_last_label` — label reused, gid fresh per box
- 🔒 **Static Non-Goal test**: `inspect.getsource` asserts the key exists only in the manual path, never in the auto-labeling landing path
- ⚡ **Read-on-demand**: setting isn't cached on a widget attribute; read live, zero state-sync code

📊 Stats: ~60 core lines + settings/integration · 9 test cases · [Details](portfolio/07-auto-person-instance.md)

---

### 8. Digit Bind Draw

**Problem**: Adding head/face to an existing person requires manually "copying" the `group_id` from the source box to each new box — slow and error-prone.

**Solution**: With `Digit Shortcut Mode = bind_draw`, select a person/head/face source box, press a digit key to enter bind-draw, and the new box inherits or backfills the source's `group_id` on commit.

**Highlights**:
- 🧩 **Self-contained manager + narrow interface**: `DigitBindDrawManager` (414 lines) holds the whole state machine; only 4 touch-points with `LabelWidget`
- ⏳ **Lazy backfill**: the source's `group_id` is *never* written at key-press; deferred to commit so backfill + new-box creation share one undo snapshot
- 🛡️ **Two-stage TOCTOU duplicate guard**: checked at key-press *and* just before commit — data changes mid-draw can't produce an illegal state
- 🚦 **Single-point boundary decision table**: boundary with module 7 short-circuits at the `handle_digit` entry, before source validation

📊 Stats: 414-line manager + integration · 19 test cases · [Details](portfolio/08-digit-bind-draw.md)

---

### 9. Precision Refinement

**Problem**: At 400% zoom, hand tremor causes 1–3px overshoot/undershoot; keyboard whole-box move can't move a single edge.

**Solution**: Mouse precision slowdown (`zoom`/`fixed`) + Ctrl temporary precision + Tab keyboard edge-select + arrow 1px / Shift+5px single-edge nudge. This is the refinement main workflow.

**Highlights**:
- 🎯 **Virtual-cursor isolation**: a separate accumulator scales delta, **never mutates `prev_point`** — hit-test/hover/transform stay zero-pollution, regression risk is zero
- 📈 **zoom mode kills stiffness**: `min(scale, max_factor)` + `max(1.0, ...)` dual clamp — at 400% it slows to 1/2 not 1/4
- ⌨️ **Tab single-edge operation**: selecting an edge makes arrows move only that edge (anti-flip clamp); `merge_window=0.5` collapses rapid presses into one undo
- ⚡ **Ctrl per-event**: unlocked mode checks the modifier per mouseMove — hold to slow, release to resume, zero state switching

📊 Stats: ~250 canvas lines + settings · 14 test cases · [Details](portfolio/09-precision-mode.md)

---

### 10. Local Edge Snap (experimental)

**Problem** (and reflection): Envisioned "refine to nearby → algorithm completes the last 1–3px via image edges", but after building it I found **image strong edge ≠ correct annotation boundary** (fuzzy person contours, clothing-texture interference, spec-required margin).

**Solution**: A one-shot command (Ctrl+Alt+E) that, for the Tab-selected edge, searches ±4 px via Sobel gradient + dual threshold (adaptive 0.6 + absolute floor 10) and snaps if both pass. **Currently experimental, not the main workflow.**

**Highlights**:
- 🧪 **Pure-Python scorer**: `edge_snap.py` (212 lines) has zero PyQt; 11 tests run without Qt
- ⚖️ **Dual threshold**: `k×local_max` (adaptive) + `abs_floor` (absolute) must *both* pass — stable across contrast levels
- 🔒 **Validate-before-apply**: if the candidate would be clamped, it's treated as failure (not partial apply) — no misleading "snap"
- 📝 **Honest self-deprioritization**: I flagged the "directional bias" and froze it as experimental — the engineering value is making "should this method even be used?" explicit

📊 Stats: 212 pure-Python lines + canvas bridge · 11 test cases · [Details](portfolio/10-local-edge-snap.md)

---

> **Modules 11–14** are early infrastructure extensions: the **Filter System** (11) and **Zoom Fix** (12) address base-experience gaps in upstream, while **Digit-Shortcut Pagination / Rename** (13, 14) extend upstream's 10-key shortcut system into a multi-page, batch-capable workflow.

### 11. Filter System (Persistence · Engine · Index · Navigation)

**Problem**: Upstream had only two bare `QComboBox`es — filters were lost on image switch, a 5,000-image workload froze on full-JSON scans, no navigation among filtered results, and logic was coupled to UI (untestable).

**Solution**: A 4-layer subsystem — `FilterState` (normalized state + snapshot/restore) / `ShapeFilterEngine` (match computation, no UI) / SQLite derived index (disposable, rebuildable) / `FilterNavigationEngine` (cross-file navigation, pure logic).

**Highlights**:
- 🔒 **Filter persistence across image switches**: `load_file()` snapshot/restore chain keeps label/gid/shape_type alive across images
- ⚡ **SQLite derived index**: 5,000 images / 18,000 shapes from frozen to instant; JSON remains the single source of truth, index is disposable/rebuildable
- 🧱 **State/Engine/UI layering**: Engine has zero PyQt, unit-testable without Qt; `filter_state_engine_pattern` is a reusable template
- 🧭 **Cross-file navigation**: jump only among files matching the active filter

📊 Stats: ~1,400 lines / 5 files · [Details](portfolio/11-filter-system.md)

---

### 12. Zoom Center Fix

**Problem**: Upstream beta.4's Ctrl+scroll zoom drifted the point under the cursor on **portrait images** — `setWidgetResizable(True)` clamps canvas width so the guard evaluates False (compensation skipped), and the y-axis misuses the width ratio.

**Solution**: Replace the width-ratio heuristic with the precise inverse of `transform_pos` (a coordinate-anchor algorithm), guaranteeing the image point under the cursor stays fixed across zoom.

**Highlights**:
- 📐 **Inverse-transform over heuristic**: `image_pos = widget_pos/scale - offset` — no `setWidgetResizable` failure path
- 🛡️ **`_clamp_scroll_value`**: when the image is smaller than the viewport (maximum==0), unreachable scroll values aren't persisted
- 📝 **Symbol-verified docs**: the design doc has a dedicated section proving `new_scroll = old_scroll + delta` preserves the invariant
- 🎯 **Honest scoping**: explicitly notes navigator methods still use the old model (deferred to Phase 2) — no "fixed everything" claim

📊 Stats: ~70 core lines + 2 analysis docs · [Details](portfolio/12-zoom-center-fix.md)

---

### 13. Digit Shortcut Pagination Extension

**Problem**: Upstream's digit shortcuts are limited to 0–9 (10 slots), but a labeling task often needs >10 label+shape_type combinations.

**Solution**: Add a pagination index layer to upstream's `create_digit_mode`; `F1` switches pages, 10×N slots, and single-page mode is fully backward-compatible with upstream.

**Highlights**:
- ⬅️ **Backward-compatible**: with the default 1 page, `get_actual_index` returns the raw digit — existing configs need zero migration
- 🔢 **Config-driven page count**: `digit_shortcut_pages` controls the slot ceiling; circular page-switch + signal notification
- 🧩 **Shared index layer**: pagination applies to all three digit modes (draw / rename / bind_draw)

📊 Stats: 311-line page manager · [Details](portfolio/13-digit-shortcut-pagination.md)

---

### 14. Digit Shortcut Rename

**Problem**: Relabeling an existing shape requires double-clicking each one to open the label dialog — prohibitively slow for batch-correcting AI pre-labels; upstream had no such capability at all.

**Solution**: In edit mode, select shapes and press a digit key — all selected shapes are instantly relabeled to that key's bound label in one batch operation.

**Highlights**:
- 🔄 **Full side-effect chain**: one rename handles undo snapshot + label update + list refresh + history + dirty flag + filter refresh
- 🔀 **Mutually-exclusive dispatch**: `digit_shortcut_mode` switches rename/draw/bind_draw; entry-point dispatch, zero conflict
- 📋 **Independent config**: `rename_shortcuts` is separate from draw's `digit_shortcuts`, no interference
- 🔗 **Pagination-aware**: also goes through `digit_page_manager`, so each page offers 10 rename slots

📊 Stats: 400-line manager + dialog · [Details](portfolio/14-digit-rename.md)

---

### 15. Viewport Persistence

**Problem**: While reviewing annotations image-by-image, you zoom into a level and focus on a region — switching images resets to fit-window, so every one of 5,000 images needs re-zooming and re-positioning. Upstream's `keep_prev_scale` keeps only the zoom ratio, not "which position am I looking at."

**Solution**: `ViewportController` caches `(zoom_mode, zoom_value, center_x, center_y)` keyed by filename, with the center stored in **image coordinates** (not scrollbar pixels) — surviving widget resizes and differing image sizes.

**Highlights**:
- 📐 **Image-coordinate persistence**: capture via `transform_pos` inverse, restore via forward transform — never stores volatile scrollbar pixels
- 🔁 **Reuses module 12's coordinate model**: the same formula pair, proven once and reused, zero new coordinate math
- 🏆 **Three-tier resolution priority**: exact history > `keep_prev_viewport` inheritance > none (fallback), with stale-state cleanup
- 🎚️ **All three zoom modes preserved**: FIT_WINDOW / FIT_WIDTH / MANUAL_ZOOM restored along with their values

📊 Stats: 359-line controller · [Details](portfolio/15-viewport-persistence.md)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| GUI framework | PyQt6 (QMainWindow / QDockWidget / QGraphicsView) |
| Quality engine | Pure Python (stdlib + PyYAML), zero PyQt dependency |
| Config-driven | YAML threshold profile + 21 pose_view config keys |
| CLI tools | argparse + ProcessPoolExecutor + tqdm |
| Testing | pytest + unittest, headless Qt (`QT_QPA_PLATFORM=offscreen`) |
| Code quality | black (line 79) + flake8 (max complexity 18) + Google docstrings |

---

## Design-Methodology Notes

While implementing these features, I distilled reusable design decisions into "pattern cards" and design docs (in Chinese):

- [PATTERN_CARD_001 Decision-to-Sort](PATTERN_CARD_001_decision_to_sort.md) — turning multi-way if-elif decisions into comparable tuple sorts
- [filter_state_engine_pattern.md](filter_state_engine_pattern.md) — single-field-driven state-machine pattern
- [canvas_refactor_plan.md](canvas_refactor_plan.md) — Canvas analysis & refactoring methodology
- [annotation_quality_methodology_prompt_guide.md](annotation_quality_methodology_prompt_guide.md) — annotation-QC methodology

---

## How to Browse This Portfolio

1. **Quick overview**: scan the Feature Matrix table above
2. **Deep dive into a module**: click the corresponding "Details" link — each contains Problem / Architecture / Highlights / File Map / Tests
3. **Design thinking**: the `docs/` directory has 116 design docs, searchable by feature-name prefix
4. **Read the code**: all `file:line` references are clickable on GitHub

---

## Acknowledgements

- [CVHub520/X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) — the excellent open-source annotation tool this fork builds upon
- All upstream contributors
