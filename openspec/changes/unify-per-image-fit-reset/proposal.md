## Why

The existing all-image viewport reset marks files for a default fit, but the fit is applied during the middle of `load_file()` while downstream display and inspector updates can still change the available viewport. The result can differ from pressing `Ctrl+F` after the image is fully settled, especially in the Label on Selection downstream workflow.

## What Changes

- Make automatic reset use the same per-image fit-window calculation as `Ctrl+F`.
- Add a post-load fit correction after downstream UI/layout work completes.
- Guard deferred corrections with the active filename and load generation.
- Reset the complete dataset list even when the file list is filtered.
- Keep `Label on Selection` as a display-only policy; it must not directly control zoom or viewport state.
- Add regression coverage for mixed image sizes, rapid navigation, filtering, and Label on Selection on/off.

## Capabilities

### New Capabilities

- `per-image-fit-reset`: Every reset target is fitted using its own image dimensions after the view is stable, with behavior equivalent to one manual `Ctrl+F`.

### Modified Capabilities

None. The existing Label on Selection behavior remains display-only.

## Impact

- `anylabeling/views/labeling/label_widget.py`: fit calculation, load lifecycle, reset target selection, and deferred correction.
- Viewport state handling remains the source of reset intent and history priority.
- Tests for viewport reset and Label on Selection integration.
