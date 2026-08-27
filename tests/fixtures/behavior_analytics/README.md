# Behavior analytics fixed fixtures

These JSONL fixtures are deterministic, local-only inputs for the measurement
quality and insight metrics contracts:

- `behavior_analytics_v1.jsonl`: legacy low-granularity input.
- `behavior_analytics_v2.jsonl`: complete semantic action and lifecycle input.
- `behavior_analytics_mixed.jsonl`: v1/v2 compatibility input.
- `behavior_analytics_low_coverage.jsonl`: missing action boundaries/context.
- `behavior_analytics_long_episode.jsonl`: anomaly diagnostic input.
- `behavior_analytics_feature_single_group.jsonl`: unavailable comparison.
- `behavior_analytics_feature_two_groups.jsonl`: control/treatment shape.
