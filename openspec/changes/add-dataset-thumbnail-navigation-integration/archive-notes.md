# Archive notes

- Implementation commit: `3ee53b35`.
- Base implementation/fix commit: `d1c654b2`.
- Rollback anchor: `1cd89e8d`, tagged `backup-before-add-dataset-label-thumbnail-browser`.

## Follow-up notes

- Fixed before archive: reverse thumbnail synchronization is disabled while virtual review playback is active.
- Remaining UI polish: digit shortcuts are ignored while a combo box or numeric editor has focus, but Qt's window shortcut may consume the key instead of forwarding it to that control. This has no annotation-data effect.
- Remaining UI polish: the existing `Image not found: %s` navigation message is not present in the translation source files.
