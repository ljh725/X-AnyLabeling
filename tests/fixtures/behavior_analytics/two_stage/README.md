# Two-stage behavior analytics fixtures

These deterministic fixtures cover the storage and replay boundaries introduced
by the trusted-recording/statistical-export pipeline:

- `monthly/events-2026-08.jsonl`: legacy v2 monthly source.
- `hourly/events-2026-08-21-01.jsonl`: v3 UTC-hour source with a manifest.
- `mixed/`: v2 monthly and v3 hourly sources with a duplicate event ID.
- `sequence_gap/events-2026-08-21-02.jsonl`: v3 sequence 1 then 3.
- `manifest_missing/events-2026-08-21-03.jsonl`: v3 source without a sidecar.
- `overlapping_actions/events-2026-08-21-04.jsonl`: overlapping action spans.
- `dual_range/events-2026-08-21-05.jsonl`: two non-overlapping UTC ranges.

The fixtures contain anonymous IDs only and no image pixels, points, paths, or
free text.
