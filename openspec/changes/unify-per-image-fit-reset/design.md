## Context

`Ctrl+F` and the current default-view path share `adjust_scale()` and `scale_fit_window()`, but the automatic path runs before the final load-time UI work has settled. The change must preserve intentional upscaling of low-resolution images while making the final result deterministic.

## Decisions

### 1. One fit implementation

Extract a single fit-window application helper used by `set_fit_window(True)`, default image reset, and post-load correction. It updates zoom mode, actions, zoom widget, canvas scale, navigator, and optional reset-origin scroll positions together.

The scale remains unconstrained above `1.0`; low-resolution images are allowed to enlarge. The available size comes from the scroll area's maximum viewport size rather than a hard-coded outer-size subtraction.

### 2. Two-stage default application

For a `FORCE_DEFAULT` or ordinary default plan, apply a synchronous fit after the pixmap is available so the new image never inherits the old scale. After the rest of `load_file()` and downstream controllers finish, queue a zero-delay correction carrying the filename and a monotonically increasing load generation. The correction runs only if that image is still current and the view is still eligible for automatic fitting.

The first successful application commits the load plan as today. The delayed correction only recomputes the final fit and updates the current UI; it does not alter annotation data or create a new viewport history entry.

### 3. Reset scope and ownership

`reset_all_image_views()` targets `_dataset_all_image_files` when available, falling back to the visible list. The viewport controller remains responsible for reset intent, history invalidation, and priority over previous-scale/previous-viewport inheritance.

`Label on Selection` remains independent. It can affect label rendering and selection presentation, but it cannot trigger or override viewport fitting. A viewport-owning review mode must explicitly declare its ownership; ordinary Label on Selection does not own the viewport.

### 4. Stale callback protection

Each load increments a generation counter. A queued fit correction checks both generation and normalized filename before touching the canvas. Dataset replacement and close/reset invalidate the generation so pending callbacks become no-ops.

## Alternatives Rejected

- Capping fit at 100%: conflicts with the requirement that low-resolution images enlarge.
- Maintaining separate reset and `Ctrl+F` algorithms: would recreate behavioral drift.
- Precomputing default zoom for every file during reset: the correct value depends on the final viewport geometry and image dimensions.

## Verification

Add Qt regression tests that compare automatic reset results with a settled manual fit for small, large, portrait, landscape, and extreme-aspect images. Add tests for filtered datasets, rapid image changes, and Label on Selection toggling without viewport side effects.
