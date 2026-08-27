# Behavior analytics requirement traceability

This table is the release checklist for the two-stage local behavior analytics
change. The implementation produces facts only; any interpretation happens
outside the application.

| Requirement / scenario family | OpenSpec tasks | Automated evidence | Manual acceptance |
| --- | --- | --- | --- |
| Local recording is opt-in, private, and loss-observable | 1.5, 2.4-2.7, 4.6, 5.3, 6.5, 11.9 | `test_behavior_analytics_privacy_contract.py`, `test_behavior_analytics_schema.py`, `test_behavior_analytics_pipeline.py` | Start with recording disabled; confirm no event shard is created. |
| Semantic action lifecycle and coverage | 2.1-3.8, 6.1-6.3 | `test_behavior_analytics_action_catalog.py`, `test_behavior_analytics_action_contract.py`, `test_behavior_analytics_e2e.py` | Replay drag, nudge, create, delete, undo/redo, AI correction, quality review, save, and A→B→A. |
| Hourly storage, manifests, gaps, retention, and old-format compatibility | 4.1-5.5 | `test_behavior_analytics_manifest.py`, `test_behavior_analytics_recorder.py`, `test_behavior_analytics_burst_retention.py` | Inspect a mixed directory and verify old monthly files are unchanged. |
| Range conversion, shard prefiltering, DST and deduplication | 7.1-7.6 | `test_behavior_analytics_pipeline.py`, `test_behavior_analytics_two_stage_fixtures.py` | Verify first/last boundary events and a non-overlapping dual range. |
| Streaming replay, quality facts, two-pass traces, and bounded tables | 8.1-9.10, 11.1-11.4 | `test_behavior_analytics_pipeline.py`, `test_behavior_analytics_measurement.py`, `test_behavior_analytics_bundle.py` | Cancel a large export and inspect manifest table limits and `other` rows. |
| Observational baseline/comparison facts | 10.1-10.5 | `test_behavior_analytics_pipeline.py` | Confirm missing groups and low samples show structured unavailable reasons. |
| Background export, cancellation, atomic publish, and no overwrite | 11.5-11.8, 12.3 | `test_behavior_analytics_bundle.py`, `test_behavior_analytics_label_widget.py` | Cancel from the progress dialog; verify no published partial directory. |
| Determinism, scale fixtures, and performance thresholds | 6.4, 12.1-12.6 | `test_behavior_analytics_pipeline.py`, `scripts/generate_behavior_benchmark_fixtures.py` | Run 1k/100k/1M fixtures on the target workstation and record thresholds. |
| Documentation and external-analysis boundary | 5.4, 11.7, 11.9, 12.7-12.9 | `test_behavior_analytics_ui.py`, `test_behavior_analytics_privacy_contract.py` | Confirm UI states “facts only” and never opens a model/upload path. |
