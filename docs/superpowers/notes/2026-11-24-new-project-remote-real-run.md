# /new-project real run on the phone (2026-11-24)

Plan `docs/superpowers/plans/2026-11-24-new-project-remote.md` Task 7 (user gate). Run by the user from Discord on the phone, 2026-11-24 23:42Z to 2026-11-25 00:02Z, against local `main` 371f660, then d7efff7 (board and ops bridge restarted on each). The user named the project `scratch` (the plan says `scratch-np`); every check below uses `scratch`.

Deviations from the plan, recorded as found:
- **No deliberate wrong-token paste.** The ops audit holds one `np_token` event (23:45:27Z, "token received") and no `token rejected` line. Two real failures were seen and retried instead (below). The acceptance item "one deliberate failure was seen and retried" is met by real failures, not by the wrong-token paste it names.
- **Failure 1, Check step: `Discord unreachable (URLError)`** (23:45:29Z, retried 23:46:01Z, same). Root cause: the board runs python.org Python 3.14, which ships no CA bundle, so `urlopen` failed `CERTIFICATE_VERIFY_FAILED`. Fixed by 64002b9 (`_ssl_context()` loads `SSL_CERT_FILE` or `/etc/ssl/cert.pem`; verification stays on), merged to main 371f660, board restarted. Retry at 23:49:09Z: `done`.
- **Failure 2, Channel step: `failed`, bridge log `create_channel scratch failed: missing permissions`** (23:49:51Z, retried 23:53:24Z and 23:54:48Z, same). Root cause: the ops bot had no server role; its permission overrides were on `#command-center` only, and creating a channel needs Manage Channels at server level (checked through the API: effective manage_channels False, manage_roles False). The user gave the bot a role with Manage Channels and Manage Roles; the next Retry: `done` (00:02:05Z).

## Preconditions

Read-only checks before the phone part (2026-11-24 ~23:35Z, after the board restart on 746a672 and `tmux-ctl discord bridge stop --ops` / `start --ops`):

```
$ tmux-ctl discord status --ops
…
bridge: running (pid 15177)
$ jq -r .guild_id ~/.local/state/agent-board/discord/_ops/bridge-state.json
1570102051021783213
$ ls ~/scratch-np ~/.local/state/agent-board/discord/scratch-np
ls: /Users/francisco.ruiz/scratch-np: No such file or directory
ls: /Users/francisco.ruiz/.local/state/agent-board/discord/scratch-np: No such file or directory
```

## Card

The setup card in `#command-center` (message 1574933642113716386, last edited 2026-11-25T00:02:10Z), final text:

```
🆕 new project scratch (new)
✅ 1. Project on disk: /Users/francisco.ruiz/scratch
✅ 2. Bot
✅ 3. Check: bot 1574933820174630913 ok · Invite: https://discord.com/oauth2/authorize?client_id=1574933820174630913&scope=bot&permissions=2252109051432000&guild_id=1570102051021783213&disable_guild_select=true
✅ 4. Joined
✅ 5. Channel: <#1574937534171975720>
✅ 6. Access
✅ 7. Start: bridge and lead started; the lead says hello in <#1574937534171975720>
Done: https://discord.com/channels/1570102051021783213/1574937534171975720
```

Failure lines seen on the card before their retries (from `~/.local/state/agent-board/discord/_ops/audit.jsonl`):

```
23:45:29Z newproject scratch:np:check   failed: Discord unreachable (URLError)
23:46:01Z newproject scratch:np:check   failed: Discord unreachable (URLError)
23:49:09Z newproject scratch:np:check   done
23:49:51Z newproject scratch:np:channel failed
23:53:34Z newproject scratch:np:channel failed
23:54:59Z newproject scratch:np:channel failed
```

No `token rejected` line: no wrong token was pasted (see the deviations above).

## Mac

Run 2026-11-25 ~00:04Z:

```
$ git -C ~/scratch symbolic-ref --short HEAD
main
$ tmux-ctl discord status --project scratch
token: set
paired: 1 allowlisted
policy: allowlist
channel: 1574937534171975720
bridge: running (pid 70290)
$ jq . ~/.local/state/agent-board/newproject/scratch.json
{ "name": "scratch", "source": "new", "dir": "/Users/francisco.ruiz/scratch", "user": "741401317943148585",
  "guild": "1570102051021783213", "bot_id": "1574933820174630913", "app_id": "1574933820174630913",
  "channel_id": "1574937534171975720", "card": "np:scratch:1",
  "steps": { disk, bot, check, joined, channel, access, start: all "done", error "" }, "done": true, … }
  (no token key; abridged)
$ grep -c "$(sed -n 's/^DISCORD_BOT_TOKEN=//p' ~/.local/state/agent-board/discord/scratch/.env)" \
    ~/.local/state/agent-board/newproject/scratch.json ~/.local/state/agent-board/discord/_ops/audit.jsonl
~/.local/state/agent-board/newproject/scratch.json: 0
~/.local/state/agent-board/discord/_ops/audit.jsonl: 0
```

Cleanup: pending. The lead's cleanup command (`tmux-ctl discord forget --project scratch`, `tmux kill-session -t '=scratch'` and `'=scratch-bg'`, `rm -rf ~/scratch ~/.local/state/agent-board/newproject/scratch.json ~/.local/state/agent-board/discord/scratch`) was refused by the auto-mode permission check at 00:05Z; it waits for the user. The user deletes `#scratch` and the scratch bot application in the portal.

## Hello

`#scratch` (channel 1574937534171975720), messages by the scratch bot, oldest first:

```
2026-11-25T00:02:18.057Z  ❓ scratch · claude: Quick safety check: Is this a project you created or one you trust?
                           → Yes, I trust this folder (from Discord)
2026-11-25T00:02:18.570Z  queue: idle · teammates: claude idle · waiting on you: none · updated 19:03
2026-11-25T00:02:37.189Z  hello from scratch
```

The plan's text is `hello from scratch-np`; with the project named `scratch` the lead posted `hello from scratch`. The user confirmed on Discord at 00:02:48Z: "Scratch says hello now". The new lead's first screen was the folder-trust dialog, answered from Discord.
