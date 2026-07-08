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
| New code | **~15,000 lines** (features + tests) |
| Test cases | **230+** (feature-related) |
| Design docs | **116** (in `docs/`) |
| Feature modules | **6** |

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
