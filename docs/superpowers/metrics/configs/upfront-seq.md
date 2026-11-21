# upfront-seq

Plans are written up front by planner agents, before the queue runs; the specs are then run sequentially as
`seq-sdd`, each from its already written plan.

```json:config
{"id": "upfront-seq", "baseline": false, "targets": [{"metric": "tokens_per_task", "max": 1.0}]}
```
