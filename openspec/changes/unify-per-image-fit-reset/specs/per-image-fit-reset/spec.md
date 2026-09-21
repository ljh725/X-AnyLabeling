## ADDED Requirements

### Requirement: Per-image fit equivalence

The application MUST calculate the final automatic fit from the currently loaded image's pixmap dimensions and the final available image viewport. Low-resolution images MAY be enlarged above 100% when that is required to fit the window.

#### Scenario: Mixed-resolution reset

- **WHEN** the user resets all image views and opens images with different resolutions
- **THEN** each image SHALL receive its own fit-window scale
- **AND** the final scale SHALL match one manual `Ctrl+F` after that image's layout is stable

### Requirement: Post-load stabilization

The application MUST perform a final fit correction after load-time downstream UI updates that can affect the available viewport.

#### Scenario: Layout changes after pixmap load

- **WHEN** a reset-target image has loaded its pixmap but inspector, selection, or other downstream UI work is still pending
- **THEN** the application SHALL recompute the fit after those updates settle
- **AND** a stale correction for a no-longer-current image SHALL do nothing

### Requirement: Complete reset scope

“Reset all image views” MUST include the complete dataset image list, even when the visible file list is narrowed by search or filtering.

#### Scenario: Filtered file list

- **WHEN** the file list is filtered and the user resets all image views
- **THEN** hidden dataset images SHALL also be marked for reset

### Requirement: Label on Selection isolation

`Label on Selection` MUST remain a display-only policy. Toggling it, changing selected/hovered shapes, or rendering fewer labels MUST NOT directly change the viewport zoom or reset state.

#### Scenario: Toggle label visibility policy

- **WHEN** the user toggles `Label on Selection` or changes the selected shape
- **THEN** the current viewport zoom and reset intent SHALL remain unchanged

### Requirement: Reset priority

A reset target MUST bypass exact history, previous viewport inheritance, and previous-scale inheritance at least once, and MUST consume that reset intent only after a successful default fit application.

#### Scenario: Reset overrides inherited view

- **WHEN** a reset target has cached history or previous-scale inheritance available
- **THEN** its next load SHALL use the default per-image fit before those fallback sources

### Requirement: Non-invasive viewport reset

Viewport reset and its deferred correction MUST NOT modify annotation geometry, dirty state, or persisted label data.

#### Scenario: Reset leaves annotations untouched

- **WHEN** the user resets one or more image views
- **THEN** shapes, dirty state, and saved label data SHALL remain unchanged
