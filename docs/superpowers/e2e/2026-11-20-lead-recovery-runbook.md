# Lead recovery and Discord commands: gate runbook (LR Task 12)

Spec: `docs/superpowers/specs/2026-11-19-lead-recovery-discord-commands-design.md`.

## Before you start

The live install links into the main checkout, so this gate runs only after the branch `feat/lead-recovery-discord-commands` is merged to `main`. After the merge:

1. Restart the board (so it writes `tasks` and `leads` into `views.json`).
2. Restart the bridge (so it registers `/lead`, `/tasks` and `/gauth`): `tmux-ctl discord bridge --ops stop`, then `tmux-ctl discord bridge --ops start`.

`<ops>` below is the bridge's ops directory (the one holding `events/` and `audit.jsonl`; `tmux-ctl discord status` shows the project's discord dir).

Rollback, if a restart leaves the window with no Claude: from another pane run `tmux-ctl lead-restart agent-board --resume`. Or, in the window itself, run `claude-orchestrator --resume <session id>` by hand (the id: `ls -t ~/.claude/sessions/*.json | head -1`, field `sessionId`, or the newest line of the project's lineage file).

## Items

### 1. `/lead status agent-board`
- Do: on the phone, send `/lead status agent-board`.
- Expect: a private reply with the lead window (`claude`) and pane, pid, busy or idle, `holds bot` yes/no, context %, and the newest handoff doc with its age. A stranger (not in `allowFrom`) gets a refusal.
- If not: the command is missing, so the bridge was not restarted (step 2 above). Reply says "no data": read `<state>/discord/views.json` key `leads` (`python3 -m json.tool`); empty means the board was not restarted. A line is also in `<ops>/audit.jsonl`.

### 2. `/lead restart agent-board` on an idle lead
Precondition: the agent-board lead is idle at its prompt (not mid-turn) and you accept it being restarted with `--resume`.
- Do: send `/lead restart agent-board`. Read the preview (window, `--resume <id>`, busy/idle). Tap **Confirm**.
- Expect: the preview message is edited to `lead-restart: agent-board restarted (resume <id>); bot: held by the new lead`. A restart that takes 20-60 s must end in this success text, not a failure (the worker has a 120 s limit). Then at the terminal: `tmux-ctl discord status` shows `held by: agent-board:claude`. Messages you send in the project channel reach the new lead.
- If the result says `bot: not held` or `no bot`: wait up to 15 min, discord-watch should restart a bot-less idle lead (two idle runs in a row) and post `agent-board lead reconnected to Discord`; check `~/.local/state/agent-board/` discord-watch log. If the window has no Claude: use the rollback line.
- If not (Confirm does nothing / `expired; run /lead again`): the preview is older than 5 min; run `/lead restart` again. Failures are in `<ops>/audit.jsonl` and the board log.
- Also check: **Cancel** on a fresh preview edits it to `cancelled` and changes nothing.

### 3. `/tasks`
- Do: send `/tasks agent-board` (a project with a running plan). Then send `/tasks` with no project.
- Expect: with a project, a private fenced block of `#id status owner tier subject` lines, subjects cut at 60 characters. Without one, a dropdown of the projects whose lead has a task list; picking one gives the same block.
- If not: `views.json` key `tasks` is empty for the project (no running `Plan & run:` task, or the board was not restarted); check `<ops>/audit.jsonl`.

### 4. One real `/gauth signal-hub-gcp`
Human gate, do not skip: confirm these values before the config is written. Then at the terminal:

    tmux-ctl gauth config signal-hub-gcp --adc --impersonate cox-agent@trk-cox-data-dev.iam.gserviceaccount.com

- Do: send `/gauth signal-hub-gcp`. A private reply carries the sign-in URL and an **Enter code** button. Open the URL, sign in, copy the code, tap **Enter code**, paste the code in the form.
- Expect: the result is posted ("Credentials saved", then `token ok`); the `gauth-signal-hub-gcp` window in `signal-hub-bg` is closed (`tmux-ctl gauth status signal-hub-gcp` shows none). A second `/gauth signal-hub-gcp` while one waits replies `a /gauth for signal-hub-gcp is already waiting for its code`. Another user, or a code after 10 min, is refused and the window closes.
- The code must never show up: `grep -c '<the code>' <ops>/audit.jsonl` is 0, and the same for the board log. Check that the token itself is not printed either (only `token ok`).
- If not: `<ops>/audit.jsonl` has the outcome; `tmux-ctl gauth status signal-hub-gcp`; close a stuck window with `tmux-ctl gauth close signal-hub-gcp`. No config: the reply gives the config hint.

### 5. discord-watch repair (only if item 2 left the bot not held, or at your choice)
- Do: none; watch. Expect `agent-board lead reconnected to Discord` in the channel within about 15 min of an idle, bot-less lead, once per 15 min at most.
