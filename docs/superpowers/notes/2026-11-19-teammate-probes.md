# Teammate request capture and hook probes (2026-11-19)

Real run for Task 1 of `docs/superpowers/plans/2026-11-19-teammate-requests-messages-dream.md`.
Claude Code **2.1.329**, Opus 5.5, effort medium, agent teams on (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`).
Everything below was observed in one scratch session; raw lines are copied from the hook dump, with only
`transcript_path`, `scratchpad_dir` and `cwd` cut where marked `…` and the scratch dir written as `$S`.

## Answers in short

| question | answer |
|---|---|
| Does the request render in the lead pane? | Yes: a normal permission dialog whose header row reads ` Bash command · from the prober agent`. |
| Must the lead be idle? | No. It rendered with the lead idle and with the lead's own tool running; behind the lead's own prompt it queued (`1 of 2` / `2 of 2`). |
| Probe A: what marks a teammate inside a hook? | No environment variable carries the name or the lead. The marker is the Claude process's command line: `ps -o args= -p "$CLAUDE_PID"` holds `--agent-name <name>`, `--team-name <team>` and `--parent-session-id <lead session id>`. The `TeammateIdle` hook input also carries `teammate_name` and `team_name`. |
| Probe B: does `UserPromptSubmit` fire in the lead for a teammate message? | No. `PostToolUse` fires in the lead only if the woken turn uses a tool. `Stop` fired in the lead after every woken turn. |

## Capture setup

    S=$(mktemp -d "${TMPDIR%/}/tmreq.XXXXXX"); git -C $S init -q; mkdir -p $S/.claude $S/dump
    # $S/.claude/settings.json: {"permissions": {"ask": ["Bash(touch probe)"]}, "hooks": {SessionStart, Stop, UserPromptSubmit,
    #   PostToolUse(*), PreToolUse(*), SubagentStop, TeammateIdle → sh "$CLAUDE_PROJECT_DIR/.claude/hookdump.sh" <Event>}}
    # hookdump.sh appends to $S/dump/hooks.log: "=== EVENT <name> pid ppid ts", "ENVNAMES <all variable names>",
    #   "ENV <NAME=value>" for names starting CLAUDE|AGENT|TEAM|AI_AGENT|TMUX (TOKEN/SECRET/KEY names left out), "STDIN <hook input JSON>"
    env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" SHELL=/bin/zsh TERM=xterm-256color LANG=en_US.UTF-8 TMPDIR="$TMPDIR" PATH=… \
      ~/.local/bin/tmux -L tmreq-cap -f /dev/null new-session -d -s tr -x 200 -y 50 -c "$S"
    tmux -L tmreq-cap send-keys -t "=tr:" 'clear; CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude --permission-mode default' Enter
    # trust dialog: Down, Enter. Prompts were typed with send-keys -l, then Enter.

`env -i` matters: the shell that ran the capture was itself a teammate and exported `CLAUDE_CODE_*` variables; the scratch
shell was checked to hold no `claude|agent|anthropic` variable before `claude` started.

Teammate mode obtained: **split pane**. The teammate was pane `%1` of the lead's window, its own process:

    tr:0.0 %0 2.1.329      (lead, 59x49 after the split; title "✳ Agent team prober touch probe")
    tr:0.1 %1 2.1.329      (teammate, 140x49; title "✳ general-purpose")

Three requests were made:

| # | lead state when the teammate asked | command | key sent in the lead pane | result |
|---|---|---|---|---|
| 1 | idle at its prompt (turn ended, `Stop` fired 2 s before the teammate's `PreToolUse`) | `touch probe` | `1` | ran; teammate sent "probe done" |
| 2 | idle at its prompt | `touch probe2` | `1` (after `resize-pane -x 120`; saved as the fixtures) | ran |
| 3 | mid-turn: the lead's own Bash prompt showing, then its tool running for 50 s | `touch probe3` | `1` on the lead's own prompt, then `3` on the teammate's | denied: teammate pane `Did not run 1 call` / `⎿  Not run · rejected` |

### Request 1, lead pane 59 columns wide (not a fixture; raw rows 20-34 of that capture)

    ───────────────────────────────────────────────────────────
     Bash command · from the prober agent
     Tip: auto mode handles these prompts for you — choose 
     "switch to auto mode" below
     Create probe file
    ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
     touch probe
    ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
     Do you want to proceed?
     ❯ 1. Yes
       2. Yes, and switch to auto mode · auto mode handles 
          these prompts for you
       3. No

     Esc to cancel · Tab to amend

Option 2 and the tip wrap at this width. The teammate pane at that moment (140 columns) showed the same box as
`team-waiting.txt` with `Action:  Create probe file` and the spinner glyph `✻` (it was `✽` in request 2: the glyph animates).

### Request 3, the queue (lead pane 120 columns)

The lead's own prompt, while the teammate's request was already waiting (header row, right end):

     Bash command                                                                                                    1 of 2
     …
     ❯ 1. Yes
       2. Yes, and don’t ask again for: python3 *
       3. Yes, and switch to auto mode · auto mode handles these prompts for you
       4. No

After `1`, with the lead's tool running (`⏺ Pause for 50 seconds using Python · 5s`), the teammate's request rendered at once:

      Pause for 50 seconds using Python · 5s
      ⎿  $ python3 -c "import time; time.sleep(50)" (6s)
         (ctrl+b ctrl+b (twice) to run in background)

    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
     Bash command · from the prober agent                                                                            2 of 2 
     Tip: auto mode handles these prompts for you — choose "switch to auto mode" below
     Create probe3 file
    ╌╌╌╌…
     touch probe3
    ╌╌╌╌…
     Do you want to proceed?
     ❯ 1. Yes
       2. Yes, and switch to auto mode · auto mode handles these prompts for you
       3. No

     Esc to cancel · Tab to amend

So the header row can carry a right-aligned `N of M` counter after the name; `2 of 2` was still on it about 5 s later
(tool row at `· 10s`) although only one request was left. The teammate's request had no "don’t ask again" row in any of the three.

## Probe A: what a hook sees inside a teammate

**Environment.** A teammate's hook has no variable holding its name, its team or its lead. The teammate's `SessionStart` hook
(pane `%1`, Claude pid 94703) against the lead's (pane `%0`, pid 92507), the variables that differ:

    teammate: ENV CLAUDE_CODE_SESSION_ATTENDED=0
    teammate: ENV CLAUDE_CODE_SESSION_ID=8898fa26-e3c4-4b54-a080-af024e206698
    teammate: ENV CLAUDE_PID=94703
    teammate: ENV TMUX_PANE=%1
    teammate: ENV CLAUDE_CODE_ATTRIBUTION_PROJECT=            (empty; also CLAUDE_CODE_USER_DELEGATED_SESSION* empty, ANTHROPIC_CONFIG_DIR, ANTHROPIC_PROFILE by name)
    lead:     ENV CLAUDE_CODE_SESSION_ATTENDED=1
    lead:     ENV CLAUDE_CODE_SESSION_ID=7bb5ac65-ad5f-4b3e-892a-d38d9a8fa8e9
    lead:     ENV CLAUDE_PID=92507
    lead:     ENV TMUX_PANE=%0

`CLAUDE_CODE_SESSION_ATTENDED=0` was the only value that told the two apart, and it says "unattended", not "teammate":
do not use it as the marker. `CLAUDE_CODE_SESSION_ID` in a teammate is the teammate's own session, not the lead's.

**Hook input (stdin).** Every teammate hook input had a top-level `"agent_type":"general-purpose"` that the lead's inputs
lack, but it is the agent type, not the name, and a `claude --agent <x>` session may carry it too. The teammate's `Stop`:

    STDIN {"session_id":"8898fa26-e3c4-4b54-a080-af024e206698",…,"permission_mode":"default","agent_type":"general-purpose","effort":{"level":"medium"},"hook_event_name":"Stop","stop_hook_active":false,"last_assistant_message":"I ran `touch probe` in `$S`, and it finished without errors. I then sent \"probe done\" to `team-lead`, and the send was confirmed. I did nothing else.","background_tasks":[],"session_crons":[]}

So `Stop` gives the last assistant message directly (`last_assistant_message`), but neither the name nor the lead.
Only the `TeammateIdle` event, which fired in the teammate process (ppid 94703) right after each of its three `Stop`s, names them:

    STDIN {"session_id":"8898fa26-e3c4-4b54-a080-af024e206698",…,"permission_mode":"default","agent_type":"general-purpose","hook_event_name":"TeammateIdle","teammate_name":"prober","team_name":"session-7bb5ac65"}

**The marker: the Claude process's arguments.** `ps` on the teammate's `CLAUDE_PID`, first run from outside the hook (same pid); the in-hook lines follow below:

    $ ps -o pid=,ppid=,args= -p 94703
    94703 92184 /Users/<user>/.local/share/claude/versions/2.1.329 --agent-id prober@session-7bb5ac65 --agent-name prober --team-name session-7bb5ac65 --agent-color blue --parent-session-id 7bb5ac65-ad5f-4b3e-892a-d38d9a8fa8e9 --lead-verify-key <redacted> --agent-type general-purpose --permission-mode default --model opus

**Read from inside a hook (fix round 1).** A second scratch run (own team `session-9339758c`, one teammate `prober`) had a
temp-repo hook on `Stop` and `PostToolUse` that, from inside the hook, ran `ps -o args= -p "$CLAUDE_PID"`, replaced the
`--lead-verify-key` value with `<redacted>` with `sed` before writing, and appended the line. Raw lines, one per hook event:

    teammate, PostToolUse (pid 39777): /Users/<user>/.local/share/claude/versions/2.1.329 --agent-id prober@session-9339758c --agent-name prober --team-name session-9339758c --agent-color blue --parent-session-id 9339758c-2f30-4d76-861c-02dcf9ac5a4e --lead-verify-key <redacted> --agent-type general-purpose --permission-mode default --model opus
    teammate, Stop (pid 39777):        /Users/<user>/.local/share/claude/versions/2.1.329 --agent-id prober@session-9339758c --agent-name prober --team-name session-9339758c --agent-color blue --parent-session-id 9339758c-2f30-4d76-861c-02dcf9ac5a4e --lead-verify-key <redacted> --agent-type general-purpose --permission-mode default --model opus
    lead, Stop (pid 30733):            claude --permission-mode default
    lead, PostToolUse (pid 30733):     claude --permission-mode default

The lead's line is the negative case: no `--agent-name`, no `--parent-session-id`. The same teammate pid showed the same line
in all three of its `PostToolUse` events and its `Stop`; the lead's pid showed the same line in both of its events.

- **Is this a teammate?** `ps -o args= -p "$CLAUDE_PID"` contains `--agent-name` and `--parent-session-id`. The lead's
  process (`claude --permission-mode default`) has neither.
- **Name:** the word after `--agent-name` (`prober`).
- **Lead session id:** the word after `--parent-session-id` (`7bb5ac65-ad5f-4b3e-892a-d38d9a8fa8e9`, equal to the lead's
  `CLAUDE_CODE_SESSION_ID` and to the `session_id` of the lead's hook inputs).
- The arguments also hold `--lead-verify-key`: a hook must cut out the two words it needs and never log the whole line.

**Second source: the team config.** `~/.claude/teams/<team_name>/config.json` (team `session-7bb5ac65`, the first 8
characters of the lead's session id, for a team the lead made without naming it):

    "leadSessionId": "7bb5ac65-ad5f-4b3e-892a-d38d9a8fa8e9",
    "leadProcess": {"pid": 92507, …},
    "members": [{"agentId": "team-lead@session-7bb5ac65", "name": "team-lead", "tmuxPaneId": "leader", "backendType": "in-process", …},
                {"agentId": "prober@session-7bb5ac65", "name": "prober", "tmuxPaneId": "%1", "backendType": "tmux", "isActive": true, "cwd": "$S", …}]

A member is matched to a hook by `tmuxPaneId` = the hook's `$TMUX_PANE` (`%1`). The team directory was gone after the
scratch server was killed (`ls ~/.claude/teams | grep -c 7bb5ac65` → 0), so it exists only while the team lives.

Not verified: an in-process teammate (no tmux) was not run; there the teammate has no process of its own, so the `ps` marker
cannot apply and its hooks, if any, would run under the lead's pid. The dev setup uses tmux teammates.

## Probe B: which lead hooks fire when a teammate message arrives

Lead-side events (`TMUX_PANE=%0`, ppid 92507) across the whole run, with the teammate's for timing:

    UserPromptSubmit ts=1795133009 %0        typed prompt 1
    PreToolUse/PostToolUse ts=…015/016 %0    Agent (spawn)
    Stop ts=1795133018 %0                    lead turn ends, lead idle
    PreToolUse ts=1795133020 %1 Bash         teammate asks (request 1); approved at ~…065
    PostToolUse ts=1795133069 %1 SendMessage teammate sends "probe done"
    Stop ts=1795133070 %1 · TeammateIdle ts=1795133071 %1
    PreToolUse ts=1795133071 %0 Bash         lead woken by the message, chose to run `ls -l probe`
    PostToolUse ts=1795133071 %0 Bash
    Stop ts=1795133073 %0                    end of the woken turn (message)
    Stop ts=1795133074 %0                    end of the second woken turn (idle notification); no tool call, so no PostToolUse
    UserPromptSubmit ts=1795133106 %0        typed prompt 2
    …
    UserPromptSubmit ts=1795133159 %0        typed prompt 3

- **`UserPromptSubmit` does not fire for a teammate message.** `grep -c 'EVENT UserPromptSubmit' hooks.log` → `3`, the three
  prompts typed into the lead; in that time the lead's transcript gained five `type: user` lines holding
  `<teammate-message>` tags (three reports and three idle notifications, the last report and notification in one line). The woken turns also keep the
  `prompt_id` of the last typed prompt (`"prompt_id":"b92f163b-e999-40d4-b844-1cd662e562aa"` on the typed prompt and on the
  `Stop` of both woken turns).
- **`PostToolUse` fires in the lead only when the lead uses a tool.** Woken by "probe done" the lead ran one Bash call:

      STDIN {"session_id":"7bb5ac65-ad5f-4b3e-892a-d38d9a8fa8e9",…,"prompt_id":"b92f163b-e999-40d4-b844-1cd662e562aa","permission_mode":"default","effort":{"level":"medium"},"hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"ls -l probe","description":"Check the probe file exists"},"tool_response":{…},"tool_use_id":"toolu_01Gin5qhdVt1CqEAfAmvwoCd","duration_ms":752}

  Woken by the idle notification it called no tool, and the only lead event was `Stop`. A busy lead (request 3) got the
  message after its running tool's `PostToolUse` (ts=1795133225), inside the same turn.
- **`Stop` fired in the lead after every woken turn**, so it is the one lead event seen for every teammate message:

      STDIN {"session_id":"7bb5ac65-ad5f-4b3e-892a-d38d9a8fa8e9",…,"prompt_id":"b92f163b-e999-40d4-b844-1cd662e562aa","permission_mode":"default","effort":{"level":"medium"},"hook_event_name":"Stop","stop_hook_active":false,"last_assistant_message":"prober has now stopped and is idle. Its final report matches what we saw: it ran `touch probe`, sent \"probe done\", and did nothing else. The task is finished.","background_tasks":[{"id":"thokkmq0x","type":"teammate","status":"running","description":"Touch probe file"}],"session_crons":[]}

- **No lead hook input names the sender.** The message itself is only in the lead's transcript (`transcript_path` of any lead
  hook input), as a `type: user` line with a timestamp whose content starts:

      "Another Claude session sent a message:\n<teammate-message teammate_id=\"prober\" color=\"blue\" summary=\"Report probe completion\">\nprobe done\n</teammate-message>\n\n…

  and the automatic idle notification is the same tag with a JSON body:
  `<teammate-message teammate_id="prober" color="blue">\n{"type":"idle_notification","from":"prober","timestamp":"2026-11-20T00:04:31.322Z","idleReason":"available","result":"I ran `touch probe` …"}`.
  The inbox files (`~/.claude/teams/<team>/inboxes/team-lead.json`) were empty lists (`[]`) once messages were delivered.
- A side event: `SubagentStop` fired in the lead after each lead `Stop`, with `"agent_type":""` and
  `"last_assistant_message":"delete the probe file"`: the prompt-suggestion subagent, not the teammate. A hook on
  `SubagentStop` must not read it as a teammate stopping.

Consequence for Task 5 (for the lead to decide; the spec says "`PostToolUse` otherwise"): `PostToolUse` alone misses a
woken turn in which the lead calls no tool; `Stop` in the lead covers it, and the time of the last message from a
teammate has to come from the transcript's `teammate-message` lines (or from the teammate's own `PostToolUse` on
`SendMessage`, whose `tool_response.routing` holds `"sender":"prober","target":"@team-lead"`), not from a lead hook input.

## Leak check

    $ tmux -L tmreq-cap ls
    no server running on /private/tmp/tmux-503/tmreq-cap
    $ ps -o pid= -p 92507,94703,92184; echo "ps_rc=$?"        # lead, teammate, tmux server
    ps_rc=1
    $ ps -ax -o pid=,args= | grep -v 'zsh -c' | grep -c 'tmre[q]'
    0
    $ ls "$TMPDIR" | grep -c tmreq
    0
    $ ls /tmp/tmux-503/ | grep -c tmreq          # after rm -f of the dead socket file
    0
    $ ls ~/.claude/teams/ | grep -c 7bb5ac65
    0

Left behind, as with the other dialog captures: a trust entry in `~/.claude.json` and two session transcripts under
`~/.claude/projects/-private-var-folders-…-tmreq-OfT0MK/` for the deleted path.
