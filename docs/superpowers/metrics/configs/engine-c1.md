# engine-c1

The queue run by the engine (`pcee-engine`, stage 3) instead of by the lead alone: the engine dispatches, reviews and
integrates, and the lead only answers asks. It is judged against the baseline on tokens per task and on the share of
tokens the lead and architect sessions spend (`control_share`, the lead's tokens plus the architect's over all tokens).

```json:config
{"id": "engine-c1", "baseline": false, "targets": [{"metric": "tokens_per_task", "max": 1.0}, {"metric": "control_share", "max": 0.5}]}
```
