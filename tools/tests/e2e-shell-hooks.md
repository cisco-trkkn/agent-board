# E2E: shell-hooks mods (kill-guard, bash-mirror, artifact-register), one real run (2026-11-05)

Run against this worktree's plugin (`--plugin-dir claude/plugin`, branch feat/mod-shell-hooks) with `claude --version` 2.1.318.
One scratch lead (haiku, auto mode) in a scratch tmux server (`~/.local/bin/tmux -L <sock> -f /dev/null`), a temp `TC_STATE`
(and `TC_LINEAGE`), a project session `shp` and a `shp-bg` session so feeds are written, started in a fresh git dir whose
trust dialog the driver answered. The driver (scratchpad `drive.zsh`, not committed) sends each prompt with
`send-keys -l "text"`, waits 1 s, sends Enter, and waits for the agent-status file to say `ready`. The lead's `--settings`
file is a copy of `claude/session-settings.json` named `sh7probe-<random>.json` with `permissions.deny = ["Bash(echo DENYRULE*)"]`.
Every `OBSERVED:` line below is printed by the driver from the scratch state dir; the raw driver output follows.

## Result summary

- OBSERVED: three markers appear under `<TC_STATE>/mods-active/` at start (`.artifact-register`, `.bash-mirror`, `.kill-guard`) and are gone after `/exit`.
- OBSERVED: one Bash call yields exactly one feed entry (the shell script defers to the mod's marker).
- OBSERVED: `pkill -f` of a pattern matching only the scratch lead is denied by the mod: the denial lists `Claude Code process(es) [<pid>]` and `No other processes match.`; the lead stays alive.
- OBSERVED: one Write of `docs/superpowers/specs/x.md` gives exactly one artifact record (kind spec, 64-hex hash, the session's id); a Write and an Edit of `a.py` give none.
- OBSERVED: a call refused by a permission rule (`Not run · permission denied`) writes no feed entry; the denied pkill writes none either.
- OBSERVED: `$.session.cwd()` lags one call behind a `cd`: the entry of `cd <sub> && pwd` shows the old cwd, the next plain `pwd` shows `<sub>`.
- OBSERVED: the entry for `sleep 3; echo late-sh7` was already in the feed when the result first showed in the pane (1 entry then, 1 entry 1 s later). This shows the entry is not written later than the result; it cannot show the result is not delayed by microseconds.
- NOT RUN (needs a human): a user-declined permission dialog. Declining is a dialog answer; the refused path is covered by the permission-rule case and the unit tests for every refusal text.
- Safety for the pkill case: before the request the driver ran `pgrep -f 'sh7probe-[<d>]<digits>'` and required exactly one pid whose command line was the scratch `claude --model haiku --settings .../sh7probe-... --plugin-dir ...` (bracketed pattern, so it matches no command line that spells it out). The check passed (see the pgrep lines below); the pattern was not widened.
- Cleanup: the tmux server was killed; `claude processes with the token: 0` and `tmux servers on the socket: 0` are in the output below.
OBSERVED: live feed log, last headers checked: 5, matching the mod's header regex: 5

## Raw driver output

```
tmp=/private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.f3HLlPRLjm sock=sh7e2e-17790 claude=2.1.318 (Claude Code)
--- lead up
OBSERVED: markers after start: 741c29ef-f737-4e98-8ce2-0e5f8712d925.artifact-register 741c29ef-f737-4e98-8ce2-0e5f8712d925.bash-mirror 741c29ef-f737-4e98-8ce2-0e5f8712d925.kill-guard
OBSERVED: feed entries for 'echo hello-sh7': 1
--- shell feed
── 18:45:59 · claude · /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.f3HLlPRLjm/work · exit 0 · @1793922359
$ echo hello-sh7
hello-sh7
--- headers after cd then pwd
── 18:46:06 · claude · /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.f3HLlPRLjm/work · exit 0 · @1793922366
$ cd /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.f3HLlPRLjm/work/sub && pwd
--
── 18:46:13 · claude · /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.f3HLlPRLjm/work/sub · exit 0 · @1793922373
$ pwd
34:❯ Run this exact Bash command and report its output: sleep 3; echo late-sh7
40:  late-sh7
OBSERVED: entries for 'sleep 3; echo late-sh7' when the result first showed: 1; 1 s later: 1
--- artifact manifest
{"ts":1793922389.387,"path":"/private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.f3HLlPRLjm/work/docs/superpowers/specs/x.md","kind":"spec","agent":"claude","hash":"fb3a2f2033770776ce1c38a89abae880035503a1d0e422f5cdbe82041313b6fd","url":"","title":"","slug":"","session_id":"741c29ef-f737-4e98-8ce2-0e5f8712d925","epoch":0}
OBSERVED: artifact records after the spec Write: 1 (kind/session: spec True claude 64;)
OBSERVED: artifact records after Write+Edit of a.py: 0 new
OBSERVED: feed entries for the rule-denied 'echo DENYRULE:x': 0
--- pane after the rule denial
❯ Run this exact Bash command and report its output: echo DENYRULE:x
  ⎿  Not run · permission denied
     │ Reason: Permission to use Bash with command echo DENYRULE:x has been denied.
⏺ The Bash command echo DENYRULE:x was denied by a permission rule, so it did not run and produced no output. I won't retry it verbatim. If you want it run, you'll need to allow it in your permission
pgrep -f 'sh7probe-[2]21952989' -> 1 pid(s): 28872
command of that pid: claude --model haiku --settings /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.f3HLlPR...
OBSERVED: pkill safety check: pattern matches exactly 1 process (pid 28872), the scratch lead
--- pane after the kill request
❯ Run this exact Bash command and report its output verbatim, including any error or refusal text: pkill -f 'sh7probe-[2]21952989'
  Ran 1 shell command
  ⎿  Not run · permission denied
     │ Reason: Permission to use Bash denied by plugins agent-board, cc-plugin-privacy: BLOCKED: `pkill -f sh7probe-[2]21952989` would also kill Claude Code process(es) [28872] (the lead, a teammate,
     │ or you). Patte…
⏺ The command was blocked before it ran. Verbatim error text:
  Permission to use Bash denied by plugins agent-board, cc-plugin-privacy: BLOCKED: `pkill -f sh7probe-[2]21952989` would also kill Claude Code process(es) [28872] (the lead, a teammate, or you).
  Patterns match full command lines, which include session names and prompts. kill by PID instead: the PID you started ($!), or `pgrep -P <your shell pid>` / `pgrep -f <pattern>` checked by hand
  first. No other processes match.
  Nothing was killed. The plugin says the pattern would also match Claude Code process 28872. I did not retry with a different command. If you want to stop the probe process, give me its PID and I can
  kill that PID directly, or I can run pgrep -f 'sh7probe-[2]21952989' first to list the matches without killing anything.
✻ Crunched for 6s · done 6:47 PM
❯
  ⚠ agent-board: 5h 10% · 7d 99% · ctx 5% · $0.01
  Haiku 5.5 · ctx 5% · 5h 10%
  ⏵⏵ auto mode on (shift+tab to cycle)
OBSERVED: scratch lead still alive after the kill request (pid 28872)
OBSERVED: feed entries mentioning the kill command: 0
OBSERVED: markers after exit: []
--- final shell feed (late entry)
$ sleep 3; echo late-sh7
late-sh7
--- done
--- cleanup check
claude processes with the token: 0
tmux servers on the socket: 0
```
