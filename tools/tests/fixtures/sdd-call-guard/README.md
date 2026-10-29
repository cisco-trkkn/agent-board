# sdd-call-guard fixtures (synthetic)

These JSONL transcripts are synthetic: placeholder text only, built to the same shape as the real events the
superpowers `pre-askuser-handoff-guard` scan reads (assistant `Skill` and `TaskCreate` tool_use blocks, and the user
message "Skill /<name> is already loaded above; instructions unchanged."). Modelled on the 2026-10-28 scratch e2e
session where round 1 (`round1-disarmed`) and round 2 (`round2-armed`) differed by the missing subagent-driven-development
Skill call. Real-state parity is checked separately, read-only, against the real transcript (see the test file).

- round1-disarmed: writing-plans, TaskCreate x2, SDD Skill call -> not armed
- round2-armed: writing-plans, TaskCreate x2, no SDD call -> armed
- no-plan: no writing-plans -> not armed
- sdd-call: the SDD Skill call alone, appended to build cycles
- second-cycle-armed / -redisarmed: plan, SDD, plan again (armed), then another SDD (not armed)
