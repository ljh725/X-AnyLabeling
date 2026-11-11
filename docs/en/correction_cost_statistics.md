# Correction Cost Statistics: User Guide

This page explains the **Correction Cost Statistics** feature in X-AnyLabeling. It records the time and operations you spend correcting annotations **inside this application**, so you can compare how costly different images or object types are.

> Scope of v1: only **plain axis-aligned rectangles**. Rotated boxes, polygons and masks are not compared (the panel reports "partial scope", see section 9).
> This is not a time-clock, not a performance-review tool, and it cannot judge how well a person worked (see sections 5 and 12).

---

## 1. Concepts: baseline, process, net result

| Term | Meaning |
| --- | --- |
| **Baseline (B)** | Rectangles already on the image when the round starts; its source is shown as replacement prediction, appended prediction or unknown source. |
| **Process cost** | How much you actually did: transactions, touches and unique objects. **Only grows** — undoing an edit or deleting a new box does not remove it. |
| **Net result** | Differences between the baseline and the current/saved result: added, deleted, geometry edits, class edits, unchanged. **Can return to zero.** |
| **Draft** | What is currently on the canvas (possibly unsaved); the panel always marks it **Unsaved**. |
| **Saved** | The most recent version successfully written to the annotation JSON. |

In short: **process = how much work you did; net = how much the result changed.** They are not interchangeable.

---

## 2. Enabling it and the statistics scope

1. Open **Settings → General → Behavior** (Basic section) and tick **Enable Correction Cost Statistics** (`correction_metrics_enabled`, `false` in the default configuration).
2. It is **off by default**. While off, no database is created, no timer runs and no event is recorded; annotation and saving are unaffected.
3. If you click the menu entry while it is off, the status bar says "Statistics are disabled. Enable them in the settings." and nothing is recorded.
4. Once enabled, open the workflow from the menu. The first open creates the statistics scope for the **dataset of the current image** and freezes that image's baseline.

**Scope = current image root + label root:**

- the status bar shows `Statistics scope — images: …; labels: …`;
- the panel's first row **Dataset** shows the root folder name (for example `images`);
- datasets are identified by both roots, so identically named files in different folders are never merged.

> Switching datasets switches the scope. Reopening the same image continues its unfinished round without freezing a new baseline.

---

## 3. The panel: live cost for the current image

When opened, the panel appears as a collapsible overlay inside the labeling window (**it is not a docked right-sidebar panel**). It is read-only about the current round and never changes your annotations. Opening it **does not steal canvas focus** and does not change the current selection or shortcuts.

### 3.1 What it shows

| Area | Content |
| --- | --- |
| Dataset | Current statistics scope (root folder name). |
| Source | Replacement prediction / appended prediction / unknown source. |
| Round | First 8 characters of the round id (hover for the full id). |
| Stage | Correction or review; a review round also shows a "Review round" tag. |
| Timer | State (Processing / Paused / Inactive / Loading / Stopped / Waiting) plus seconds. |
| Counts | Initial boxes (baseline), current boxes. |
| Operations | Transactions, unique objects, touches. |
| Current draft | Added / deleted / geometry edits / class edits / modified originals / modified rate, with an **Unsaved** badge. |
| Saved result | The same six values for the last successfully saved version. |
| Completion | Completion state; once complete the time row becomes "frozen time at completion" and a completion record id is shown. |
| Quality | Quality assessment (default: **Not assessed**) with the note "Finishing a round is not a quality approval"; an existing review mark is shown on its own row. |
| Record integrity | Comparable (yes/no), limitations (`issues`), and recording problems (for example a failed statistics write). |

### 3.2 Buttons

| Button | Action |
| --- | --- |
| Start recording / Pause timer / Resume timer | Switches according to the current timer state. |
| Finish round | Enabled only when the round is saved, clean and unfinished; otherwise disabled with the reason in its tooltip (e.g. "Save the current version before marking it complete"). |
| Continue correction | Appears once the round is complete; revokes completion and resumes timing. |
| Start review | Opens a **separate review round** for the same image, counted apart from correction; inside it the finish button reads "Finish review". |
| Report | Opens the summary dialog (section 10). |

### 3.3 Idle confirmation (never blocks, never auto-deducts)

- After **120 seconds** without input, a bar appears: "Was this period spent reviewing?"
- It is a **prompt only**: it does not deduct time and does not block you (non-modal, never steals focus). The bar stays in the panel until you choose "Count as work" or "Exclude idle"; it also disappears when the round ends or the panel is collapsed.
- Two choices:
  - **Count as work** — the idle period counts as review time (process time unchanged);
  - **Exclude idle** — the idle period is subtracted; the excluded seconds are disclosed in the time row's tooltip.
- One answered segment is never asked again; a later idle segment asks again.

---

## 4. Process cost versus net result

- **Transactions**: one completed operation = one transaction. Batch-reclassifying 10 objects is still **1 transaction / 10 touches / 10 unique objects**.
- **Touches**: object-operation pairs (the same object edited twice counts twice).
- **Unique objects**: distinct objects affected (counted once however often they were edited).
- **Net result** compares only the baseline and the result objects/geometry/class — independent of how many operations were needed.
- Typical cases:
  - add a box and delete it again: process cost stays, net result returns to zero;
  - drag a box and undo: process cost stays, the box is "unchanged" again;
  - panning/zooming the view or selecting objects: **no cost recorded**.

---

## 5. What the numbers mean

- The panel shows **in-application processing time**, not real working hours and not eye-tracking. It only counts time while this application is in the foreground and the image is interactive.
- The timer stops on explicit pause, switching to another application, screen lock/suspend, or while the image is still loading. Resuming never back-fills the time you were away.
- **Blocking waits** (loading, genuine modal blocks) are listed separately and never mixed into processing time.
- **120 s without input** only prompts (section 3.3); time is deducted only if you choose "Exclude idle", and an adjustment record is kept.
- **Background inference while you review** is recorded separately: it is neither subtracted from your time nor added to it to fake a wall-clock total.
- Therefore **do not use these figures for individual performance conclusions**; compare similar images and similar workflows instead.

---

## 6. Existing annotations of unknown origin

- Annotations that existed before statistics were enabled get the source **unknown source (disclosed only)**.
- This only means the boxes predate the statistics. It does not infer which model produced them and does not back-fill historical time.
- Unknown origin is **disclosure only** and does not block a full comparison; other gaps (storage gap, external change, …) do (section 9).

---

## 7. Class renames, merges and splits

- A **one-to-one global rename** (A → B) does not count as a personal class edit; the comparison stays comparable.
- Personal class edits you made **before** the rename are preserved; the new mapping never rewrites history.
- **Merge/split** (e.g. A and B merged into X) marks the affected class comparison **not comparable**: class counts, unchanged counts and their rates become **N/A** (not 0). Geometry metrics such as added/deleted/geometry edits remain valid.

---

## 8. Denominators and N/A

- **Changed-original rate** = modified originals / baseline rectangle count (B).
- **Unchanged rate** = unchanged / baseline rectangle count (B).
- When the baseline is empty (B = 0) or classes are not comparable, these rates are **N/A**, never 0.
- **Added objects are listed separately** and are not "modified originals"; the parts cannot be summed into a modified total.
- Anywhere you see `N/A` it means "cannot be computed / not comparable"; `0` means "genuinely zero".

---

## 9. Record integrity (`issues`)

The panel and the report label why a record is incomplete:

| Label | Meaning | Blocks a full comparison? |
| --- | --- | --- |
| Partial scope | The image contains non-rectangle objects, or a shape changed type | Yes |
| Type conversion | An object changed between rectangle and another type during the round | Yes |
| Statistics write gap | Statistics DB write failed or the queue overflowed; events were lost | Yes |
| Annotations changed externally | The annotation file changed outside the application | Yes |
| Image content changed | The image content differs from the version the baseline was frozen on | Yes |
| Interrupted timing | A timing segment was not closed normally (e.g. after a crash) | Yes |
| Interrupted draft | An unsaved draft was restored or discarded | Yes |
| Class mapping not comparable | Class vocabulary merged/split or a conflicting mapping | Yes (class metrics only) |
| Object identity conflict / invalid geometry | Duplicate object ids or invalid coordinates | Yes |
| Unknown source (disclosed only) | The baseline predates the statistics | **No — disclosure only** |

> Rule: when a record is incomplete, **do not treat it as a full comparison**. The report can filter to comparable records only.

---

## 10. Summary and CSV export

Click **Report** on the panel to open the summary dialog with three tabs:

1. **Image rounds** — one row per image/round (image, round, stage, source, model and version, class vocabulary version, initial/final counts, per-kind counts and rates, time, completion/quality, limitations).
2. **Class changes** — directions (initial class → final class), object counts, denominators and comparability.
3. **By density and model** — grouped by final rectangle count and model version; only comparable saved rounds are counted.

**Filters**: range (current results / history / all), model version, stage, and search boxes for class/image/model.

**Export** (export menu at the top right, three CSVs):

| File | Content |
| --- | --- |
| Image round details CSV | Detail rows matching the Image rounds tab |
| Class change details CSV | Direction details matching the Class changes tab |
| Metric dictionary CSV | One row per field (`field, meaning`) |

- Encoded as **UTF-8 with BOM** so spreadsheet tools open Chinese correctly; text fields are escaped against formula injection.
- The export is a **frozen snapshot**: what you saw when you clicked export is exactly what gets written; edits made during the export never leak into that file.
- Exporting runs in the background with progress; **cancelling or failing never leaves a file that pretends to be complete**.
- There is no PDF export, and v1 has no automatic quality scoring.

---

## 11. Reproducible example (30-rectangle synthetic sample)

The numbers below come from a **self-made synthetic sample** (640×640 noise background plus 30 colour blocks, six classes, five each). They are **not real data**; they only show how the numbers relate. The generator and script live in the repository's sample-design document.

Baseline: 30 rectangles, source = replacement prediction (`ai_count = 30`).
One scripted round: drag 5 boxes, reclassify 4 objects one by one (one of them was also dragged), batch-delete 2, batch-create 2.

| Metric | Value |
| --- | --- |
| Initial rectangles B | 30 |
| Final rectangles F | 30 |
| Added | 2 |
| Deleted | 2 |
| Geometry edits | 5 |
| Class edits | 4 |
| Modified originals (unique) | 10 |
| Unchanged | 20 |
| Changed-original rate | 33.3% |
| Unchanged rate | 66.7% |
| Transactions | 11 |
| Touches | 13 |
| Unique objects | 12 |
| Limitations | none (fully comparable) |

How to read it: the 11 transactions include one batch delete (2 objects) and one batch create (2 objects), giving 13 touches; one object was dragged and then reclassified (2 transactions, 1 unique object), giving 12 unique objects. Net 10 = 2 deleted + 8 originals involved in a geometry or class edit (1 of which was both moved and reclassified, so it is not counted twice).

If this round is **not saved yet**: the draft view still shows the values above with an **Unsaved** badge, while the saved view shows **N/A** for the net fields and the limitation "result not saved".

---

## 12. Known limitations

- **Finishing a round is not a quality approval**: quality defaults to "not assessed"; only an explicitly sourced quality conclusion is recorded.
- The panel is a **collapsible overlay** inside the labeling window, not a separate window, and it does not dock into the right sidebar; with a lot of data it gets tall, so collapse it if needed (only the title row remains).
- **UI languages**: the feature ships built-in copy in Chinese, English, Japanese and Korean, but the compiled `.ts/.qm` catalogues have not been rebuilt yet, so some builds may still show the Chinese source strings or English.
- **Only plain axis-aligned rectangles** are compared; rotated boxes, polygons, masks and points are excluded.
- No mouse trails, typing frequency or employee identity are collected; no ranking, accuracy or "money saved" estimates are produced.
- The statistics database and the annotation files are separate; a statistics problem never breaks annotation saving, but "saving succeeded" does not guarantee "statistics are complete" (section 9).

---

## 13. FAQ

**Why is the net result all N/A?**
Usually the round is not saved yet (check the draft view), the class vocabulary is not comparable, or the record is incomplete (check the limitations). N/A means "do not draw a conclusion", not "no change".

**Why did I do a lot of work but the net result is small?**
Process cost and net result are separate. Repeated adjustments and undos add process cost, while the net result only compares the final result with the baseline.

**Do I lose data if I turn the feature off?**
No. Turning it off only stops collection; the existing local statistics database is kept and can still be exported.

**Can I use these times as working hours?**
No. It is in-application processing time: it excludes pen-and-paper work, offline thinking and work in other applications, and says nothing about attention or effort quality.
