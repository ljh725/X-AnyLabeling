# Annotation appearance and safe label batch editing

## Appearance modes

The display mode is a user preference and does not modify annotation JSON:

- **Focus** (default): select one valid `group_id` to emphasize the complete
  person/head/face group and dim unrelated visible objects.
- **Label**: stable project label colors.
- **Group**: stable group colors for overview; `group_id=0` is a normal visible
  color, not a background slot.
- **Instance**: stable session colors per shape.
- **Uniform**: one low-noise base color for geometry-focused review.

Rectangle rendering uses a dark outer contrast stroke plus a semantic inner
stroke. Normal fill is disabled by default; selected and hovered fills are
independent low-opacity channels. Label and GID text are optional identity
helpers, so color is never the only way to distinguish an object.

User display preferences are stored under `annotation_appearance` in the user
configuration. Shared label colors are stored in
`.xanylabeling/appearance.yaml` below the annotation root. No appearance or
focus state is written into shape JSON, undo history, dirty state, or quality
reports.

## Label manager safety model

The label manager edits an isolated draft. Confirmed changes are classified
before execution:

- Color/visibility-only changes update the project sidecar and perform one
  canvas refresh; annotation JSON is not read or rewritten.
- Rename/delete changes run in a background worker. Candidate discovery and
  staging are cancellable; the short atomic commit phase is explicitly
  non-cancellable.
- Only files with verified matching shapes are staged. Every staged file is
  re-parsed, backed up, and atomically replaced. A versioned manifest under
  `.xanylabeling/transactions/<id>/manifest.json` retains recovery information.
- Partial success is reported with succeeded, failed, skipped, and cancelled
  counts. The current file and label summary are rebuilt from disk after a
  successful migration.

Renaming to an existing label requires explicit merge confirmation. Deleting a
label is a dataset mutation and should be reviewed with the affected file and
shape counts before confirmation.

