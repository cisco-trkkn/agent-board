# Lead recovery and Discord commands: gate runbook (LR Task 12)

Spec: `docs/superpowers/specs/2026-11-19-lead-recovery-discord-commands-design.md`.

## Before you start

The live install links into the main checkout, so this gate runs only after the branch `feat/lead-recovery-discord-commands` is merged to `main`. After the merge:

1. Restart the board (so it writes `tasks` and `leads` into `views.json`).
2. Restart the bridges (so they register `/lead`, `/tasks` and `/gauth`; both the ops bot and each project bot offer them): `tmux-ctl discord bridge --ops stop`, then `tmux-ctl discord bridge --ops start`; for a project bot the same without `--ops`.

`<ops>` below is the ops bot's directory, `~/.local/state/agent-board/discord/_ops/`. It holds `views.json`, `audit.jsonl`, `events/` and `gauth-pending.json`. It is not the project's discord dir that `tmux-ctl discord status` shows. A command sent to a project bot is logged in `~/.local/state/agent-board/discord/<project>/bridge.log` and audited in `~/.local/state/agent-board/discord/<project>/audit.jsonl`; the ops bot's are in `bridge.log` and `audit.jsonl` under `<ops>`. Wherever an item below says `<ops>/audit.jsonl`, read the bot's own file you sent the command to.

Rollback, if a restart leaves the window with no Claude: from another pane run `tmux-ctl lead-restart agent-board --resume`. Or, in the window itself, run `claude-orchestrator --resume <session id>` by hand (the id is the one of THIS pane's lead, not the newest session of any project: `P=$(tmux display -p -t '=agent-board:claude' '#{window_id}.#{pane_id}')`, then `for f in ~/.claude/sessions/*.json; do jq -r --arg p "$P" 'select((.tmux // "") | endswith($p)) | "\(.updatedAt) \(.sessionId)"' "$f"; done | sort -n | tail -1`; the second field is the id. This is how `relay.session_for_pane` picks it).

## Items

### 1. `/lead status agent-board`
- Do: on the phone, send `/lead status agent-board`.
- Expect: a reply of four lines in a fenced block: `window claude · pane %N · pid N`, `state idle · bot held` (or `not held`), `context N%` (or `unknown`), `newest handoff <file> (<age> ago)` (or `none`). A stranger (not in `allowFrom`) gets `Not authorized.`.
- If not: the command is missing, so the bridge was not restarted (step 2 above). Reply `no lead info for agent-board`: read `<ops>/views.json` key `leads` (`python3 -m json.tool`); empty means the board was not restarted.

### 2. `/lead restart agent-board` on an idle lead
Precondition: the agent-board lead is idle at its prompt (not mid-turn) and you accept it being restarted with `--resume`.
- Do: send `/lead restart agent-board`. Read the preview (`restart the agent-board lead in window claude with --resume <id>`, plus `; it is <state> right now` when not idle). Tap **Confirm**; the message first reads `running…`.
- Expect: the message ends as `lead-restart: agent-board restarted (resume <id>); bot: held by the new lead`. A restart that takes 20-60 s must end in this success text, not a failure (the worker has a 120 s limit). Then at the terminal: `tmux-ctl discord status` prints `held by: agent-board:claude pid <N>`. Messages you send in the project channel reach the new lead.
- If the result says `bot: not held` or `no bot`: wait up to 15 min, discord-watch should restart a bot-less idle lead (two idle runs in a row) and post `agent-board lead reconnected to Discord`; check the discord-watch log (`~/.local/state/agent-board/discord-watch.log`). If the window has no Claude: use the rollback line.
- If not (Confirm answers `expired; run /lead again`): the preview is older than 5 min; run `/lead restart` again. A second tap on the same button answers `already confirmed`. Failures are in `<ops>/audit.jsonl` and the board log.
- Also check: **Cancel** on a fresh preview edits it to `cancelled` and changes nothing.

### 3. `/tasks`
- Do: send `/tasks agent-board` (a project with a running plan). Then send `/tasks` with no project.
- Expect: with a project, a fenced block of `#id status owner tier subject` lines, subjects cut at 60 characters. Without one, on the ops bot (and on a project bot anywhere but its own channel), a `Pick a project` dropdown of the projects that have a task list; picking one gives the same block. A project with none replies `no task list for <p>`; with no project at all, `no task lists`. A project bot's `/tasks` with no project shows its own project's list in its own channel; anywhere else, and on the ops bot, the Pick a project dropdown.
- If not: `<ops>/views.json` key `tasks` is empty for the project (no running `Plan & run:` task, or the board was not restarted); check `<ops>/audit.jsonl`.

### 4. One real `/gauth <project>`
Works for any GCP project and account. Human gate, do not skip: the user picks the project and the mode, and confirms them before anything is written or run. (Example, one of many: project `signal-hub-gcp` with a service account to impersonate.) Then at the terminal, one of:

    tmux-ctl gauth config <project> --adc --impersonate <sa-email>    # ADC login, token checked as that service account
    tmux-ctl gauth config <project> --adc                             # ADC login, no impersonation
    tmux-ctl gauth config <project> --no-adc --account <email>        # plain `gcloud auth login` for that account

`tmux-ctl gauth config` prints `gauth: config written <path>: <argv>`. The argv must be `gcloud auth application-default login --no-launch-browser [--impersonate-service-account=<sa>]` for `--adc`, or `gcloud auth login --no-launch-browser --account=<email>` for `--no-adc --account`. (`--adc --account` drops the account: use `--no-adc` with `--account`.)

- Do: send `/gauth <project>`. A private reply carries `Open this URL, sign in with Google, then press Enter code and paste the code (valid 10 min):`, the URL and an **Enter code** button. Open the URL, sign in, copy the code, tap **Enter code**, paste the code in the form. The form answers `Code sent.`.
- Expect: a private reply `authenticated: token ok`; the window `gauth-<project>` in the session `<project>-bg` is closed (`tmux-ctl gauth status <project>` prints `gauth: idle`). The window's own line (`Credentials saved` for ADC, `You are now logged in as` for `--no-adc`) is not posted. A second `/gauth <project>` while one waits replies `a /gauth for <project> is already waiting for its code`. A code after 10 min replies `gauth for <project> timed out; run /gauth again` and closes the window. A code entered by another allowlisted user is ignored silently: no reply, and the window stays open for the requester (a user not on the allowlist is rejected and audited `rejected`). Wrong code: `auth failed: ERROR: …`.
- Check that the board's PATH reaches gcloud: the reply must say `token ok`; `could not run gcloud: FileNotFoundError` means it does not.
- The code must never show up: `grep -c '<the code>' <ops>/audit.jsonl` is 0, and the same for the board log. The token itself is not printed either (only `token ok`).
- If not: `<ops>/audit.jsonl` has the outcome; `tmux-ctl gauth status <project>`; close a stuck window with `tmux-ctl gauth close <project>`. No config: the reply says `no gauth config for <project>; set it at the terminal: tmux-ctl gauth config <project> …`.

### 5. discord-watch repair (only if item 2 left the bot not held, or at your choice)
- Do: none; watch. Expect `agent-board lead reconnected to Discord` in the channel within about 15 min of an idle, bot-less lead, once per 15 min at most.
