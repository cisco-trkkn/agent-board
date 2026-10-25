# Spike: GitLab Issues/Boards as the ticket tracker (tracker-scout, 2026-10-25)

## Recommendation

- Use GitLab as the system of record for **work that outlives a session** and keep the local files as the working copy. Nothing new is built; the integration point is the existing `board/ideas.py` (called by `tmux-ctl idea` and the board's Ideas box), shelling out to `glab`.
- Mapping: idea → issue (label `idea`); spec → issue or epic (label `spec`) linking the spec file; plan → epic; plan task → child issue of that epic (task issue type); sprint → iteration; backlog → open issues with no iteration, ordered on a board; milestone → release/phase.
- Direction: **push only, local → GitLab**, one `gl:<iid>` back-reference stored on the local line/task (no pull-sync). Status flows back only by explicit `glab` close at idea `[x]/[-]` and task completion.
- Phase 1 (smallest): `ideas.py add --issue` creates the issue via `glab issue create` and appends `· #123` to the line. Phase 2: plan-task sync skill. Skip the MCP for automation (OAuth, interactive, not scriptable); keep it for ad-hoc reads in chat.
- Measured: the `trkkn` group appears to be **Premium or better** (epics/iterations endpoints answer 200, not 403) but the plan field is hidden from this token. Nothing is configured yet (0 issues, 0 labels, 0 boards, 0 milestones, 0 cadences), so any scheme is greenfield.

## What the account supports

Logged in as `francisco.ruiz6`, access level 40 (Maintainer) on `trkkn/trkkn-na/master-gcp-repo`. GitLab 19.6.0-pre (gitlab.com).

| Question | Call | Result |
|---|---|---|
| Auth | `glab auth status` | logged in to gitlab.com, token in keyring (redacted) |
| Tier | `glab api groups/trkkn` (`plan`) ; `glab api namespaces/trkkn` | `plan: null`, `trial: null`: **not visible** to a non-owner token. Tier is therefore inferred, not read |
| Epics | `glab api groups/14414303/epics?per_page=1` | `200 []` (Free returns 403/404) → licensed |
| Iterations | `glab api groups/trkkn/iterations?per_page=1` | `200 []` → licensed, none exist |
| Iteration cadences | GraphQL `group{iterationCadences{nodes{id}}}` | `nodes: []` |
| Milestones | `glab api groups/trkkn/milestones` | `200 []` (milestones exist on all tiers) |
| Boards | `glab api projects/<id>/boards` | `200 []` (only the implicit default; none created) |
| Labels | group + project label lists | 0 labels (scoped labels `a::b` are Premium; cannot be proven read-only) |
| Issue widgets | GraphQL `workItemTypes{widgetDefinitions}` | Issue has `ITERATION`, `WEIGHT`, `STATUS`, `HIERARCHY`, `MILESTONE`, `CUSTOM_FIELDS`; Epic has `HIERARCHY`, `WEIGHT`, `START_AND_DUE_DATE`. Work item types: Epic, Incident, Issue, Task, Ticket |
| Issues enabled | `GET projects/<id>` | `issues_enabled: true`, `open_issues_count: 0` |
| Rate limit | `glab api -i ...issues` | `Ratelimit-Limit: 2000` per window (`throttle_authenticated_api`), 1971 remaining |

Gap: the plan could be confirmed only by a group Owner (Billing page) or by creating an iteration cadence (a write; not done). Ask the lead if a write test is wanted. If it turns out Free, fall back to: milestones as sprints, plain labels (`sprint-12`, `status-doing`), no epics (use a parent issue with task list).

## Mapping

| Today | GitLab | Direction / notes |
|---|---|---|
| Idea `- [ ] date · text` | Issue, label `idea`; detail lines → description | local → GitLab on add. Local line gets ` · #<iid>` suffix |
| Idea `[x] … → spec` | Issue gets label `spec`, comment with spec path (or closed if the spec ships); optionally promoted to an Epic | local → GitLab, on take-up only |
| Idea `[-]` dropped | Close issue as "not planned" | local → GitLab, one-way |
| Spec `docs/superpowers/specs/*.md` | Epic (or issue) whose description links the file (repo URL + commit); file stays the source of truth | local → GitLab; never copy the body |
| Plan `plans/*.md` | Epic (child of spec epic) | local → GitLab at plan-write |
| Plan task `*.md.tasks.json` (id, subject, status, blockedBy) | Child issue (Task type) of the plan epic; `subject` → title; `status` pending/in_progress/completed → label `doing` / close; `blockedBy` → "is blocked by" link | local → GitLab at plan-write and task-complete; `tasks.json` gains a `gitlab_iid` field (not in current files: keys seen are planPath, tasks[].id/subject/status/description) |
| Sprint | Iteration (cadence of 1–2 weeks) | GitLab-owned; humans assign issues; local never writes it |
| Backlog | Open issues with no iteration; a board "Backlog" list | GitLab-owned |
| Phase / release | Milestone | GitLab-owned |

## Integration options

1. **Extend `ideas.py` / `tmux-ctl idea` / Ideas box with `glab`.** Add an optional `--issue` flag (or per-project config `gitlab: group/project`) that runs `glab issue create -t ... -l idea` and records the iid; board adds a "Create issue" button on a line. Effort: small (~1 file + tests; the file already has locked append and a stale-key model). Risk: low; failure of `glab` must not block idea capture (queue and retry).
2. **GitLab MCP (`gitlab` plugin).** Plugin `.mcp.json` points to the remote server `https://gitlab.com/api/v4/mcp` (http, OAuth). In this session only `authenticate` and `complete_authentication` are exposed until the user signs in, so the tool list could not be measured without an interactive login (flagged). Effort: none to install, but it is chat-time only, interactive auth, and cannot be called from `tmux-ctl`/board code. Best as a read/ad-hoc complement. Risk: tool surface unverified; OAuth scope grants write on every repo.
3. **Sync skill (plan-write and task-complete).** A skill (or script run by the plan skills) reads `tasks.json`, creates the epic and child issues with `glab`, writes `gitlab_iid` back, and closes issues on completion. Effort: medium (idempotence, blockedBy links, partial-failure resume, tests with a fake `glab`). Risk: highest: duplicates when a plan is rewritten, and `tasks.json` is rewritten by other tools, so the iid must survive.

Suggested order: 1, then 3. Use `glab` rather than raw REST; it already handles auth and `--repo`.

## Risks

- **Duplicates:** re-running add or sync without a stored iid creates twins. Mitigation: write the iid before reporting success; search by a `<!-- agent-board:id -->` marker in the description before creating.
- **Two sources of truth:** statuses drift if humans edit issues. Mitigation: push-only for text, GitLab-owned for iteration/milestone/assignee; never read them back into files.
- **Rate limits:** 2000 requests per window per user; one create per idea/task is far below. Batch plan sync serially and stop on 429 (check `Ratelimit-Remaining`).
- **Client-confidential text:** ideas and task descriptions carry client names and code detail; issues are visible to every member of the group (`trkkn` has MENA and NA subgroups, private visibility). Mitigation: opt-in per project, title-only by default (no detail lines), and a confirm before the first push; do not push from the shared `francisco_ruiz` ideas file.
- **Notifications/noise:** every create/close emails watchers; the 100+ historical ideas should not be bulk-imported.

## Method

Read-only calls only; nothing was created, edited or closed.

```
glab auth status
glab api groups/trkkn ; glab api namespaces/trkkn
glab api groups/trkkn/subgroups
glab api "groups/14414303/epics?per_page=1" ; groups/trkkn/iterations ; groups/trkkn/milestones ; groups/trkkn/labels
glab api projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo ; .../boards ; .../issues ; .../labels ; .../members/all
glab api -i ".../issues?per_page=1"        # rate-limit headers
glab api graphql  (iterationCadences, epics count, milestones, workItemTypes/widgetDefinitions)
glab api version
cat ~/.claude/plugins/cache/anthropic-plugin-directory/gitlab/*/.mcp.json
sed board/ideas.py ; grep idea bin/tmux-ctl ; read a *.md.tasks.json
```
