# Remote iPad control of the Agent Board over Tailscale

Idea (agent-board inbox, 2026-11-02): "building on the overview feature … remotely control these sessions from my phone", with the note "SSH is restricted on my work laptop, i have ourchased an ipad mini 6 already". Derived from a ChatGPT conversation the user shared ("Remote Tmux Options"): host is a Mac, goal is to operate the existing dashboard and control agents, access from anywhere including cellular.

**Status: Stage 0 is BLOCKED.** Tailscale cannot be installed on the work MacBook yet (Jamf-managed, user is not admin; IT verbally approved but the app is not installed). Everything below is designed so it can be built and tested up to the point of needing the real tailnet; the steps that need HTTPS over the tailnet are human gates after Stage 0. This spec does not authorise any userspace/unmanaged Tailscale install; the supported install (Self Service / IT push of the standard app) is the only route.

## Problem

The Agent Board (`board/`) runs on `127.0.0.1` and is reachable only on the Mac. The user wants to watch every project and control its agents from an iPad mini on cellular or public Wi-Fi, without SSH (restricted) and without weakening the board's localhost-only security model.

## Decisions (user, 2026-11-02)

- **Exposure:** Tailscale Serve as a single HTTPS origin, reverse-proxying the board (7700) and later ttyd (7701). Not a direct tailnet bind; not Funnel.
- **Terminal:** the embedded live terminal is deferred to a later stage. v1 is the Overview, per-project detail, and actions.
- **Control scope:** full control from the iPad (everything `/api/action` offers), with confirms on destructive actions.
- **Auth:** the tailnet (device auth) plus the existing secret URL token, plus per-action confirms. No separate app login in v1; a clean seam is left to add one.
- **Layout:** single scrolling list of project cards with inline actions (mockup B).
- **Confirm style:** inline confirm strip on the card (mockup A), with the Confirm control shifted from the trigger's position so a double-tap can't pass, and worst-case actions naming their exact target.

## Architecture

```
iPad Safari (Home Screen web app)
   │  https://<mac>.<tailnet>.ts.net/<token>/
   ▼
Tailscale Serve  (TLS termination, MagicDNS cert, tailnet-only; never Funnel)
   ├── /<token>/        → 127.0.0.1:7700   board: page + JSON API
   └── /<token>-tty/…   → 127.0.0.1:7701   ttyd (Stage 4 only)
   ▼
tmux + Claude agents (unchanged)
```

- The board and ttyd keep binding `127.0.0.1`. Serve is the only tailnet-reachable surface; the localhost bind stays as defense in depth.
- One browser origin (`https://…ts.net`): the token-in-path model is unchanged, the page is a secure context (browser notifications and secure cookies work), and the Stage 4 terminal is same-origin instead of `127.0.0.1:7701`.

## Board changes (v1, `board/server.py` + startup glue)

1. **Host allowlist becomes configurable.** Today `ALLOWED_HOSTS = {127.0.0.1:PORT, localhost:PORT}`; a non-match returns `421 bad host`. Add names from an env var (e.g. `TMUX_DASH_EXTRA_HOSTS`, comma-separated) at startup, merged with the localhost entries. The check stays as the anti-DNS-rebinding mechanism.
   - **Implementation spike:** confirm what `Host` header Tailscale Serve forwards (the `…ts.net` name vs a rewritten `127.0.0.1:7700`); the allowlist handles either once observed.
2. **Secure context:** no code change — HTTPS via Serve makes Safari treat the page as secure, so the overview's `Notification` flow (already feature-detected) lights up. The spec records this as *why* Serve is required, not a convenience.
3. **CSRF stays covered:** state-changing calls use the `X-Dash-Token` **header** (not a cookie); no permissive CORS is ever added. Recorded as a constraint.
4. **The token is now a remote credential:** keep it out of logs; document a one-line rotation; losing the iPad means rotate the token and drop the device from the tailnet.
5. **Terminal/CSP untouched in v1** (`frame-src`, ttyd base URL change only in Stage 4).

## iPad UI (Stage 3)

- **Layout B:** one scrolling list of project cards, ordered needs-you → working → rest, name-sorted within a group (reuses the Overview's `ovSorted`/`ovGroup` and digest). Each card: project, status chip, spend, a snippet of latest output, and the action row. Responsive; the existing `@media (max-width:900px)` is the base.
- **Action row per card:**
  - One tap (reversible/low-blast): `ask_shutdown`, request status report, idea edits, artifact move.
  - Inline confirm (A): `stop_agent`, `restart_orchestrator` (uses the server's existing `confirm` flag), `remove_worktree`.
  - Inline confirm + target echoed: `close_session`, `remove_safe_worktrees`.
  - Free-text `send`/`tell`: a collapsed "Send text" expanding to a field with the target window named above it; never a single tap; first candidate for the login seam.
- **Confirm strip (A):** replaces the button row in place, names the exact target ("Stop worker 2 in interiors — mid-task"), Confirm rendered shifted from the trigger. No bottom sheet.
- **Audit log:** every iPad-triggered action writes one line (action, time, target session/window, outcome; no secrets).

## Security model

- The gate for actions is: on the tailnet AND holding the secret URL. No second factor in v1.
- **Residual risks (recorded, with mitigations):** lost iPad (rotate token + drop device); shared tailnet (a Tailscale ACL limiting the Serve target to the user's own devices — required in Stage 0); token in history/logs (keep out of logs; mode-600 on disk).
- **Kept, must not regress:** header-token (not cookie) for actions, no permissive CORS, Host allowlist.
- **Login seam:** all actions pass one server-side authorization choke point, so a passkey/password is one later layer, not a rewrite. Free-text `send`/`tell` is the action most worth that login.

## Reachability

- `caffeinate` already keeps the Mac awake on power. A `launchd` agent restarts `tmux-dash` and `tailscale serve` after crash/logout/reboot. Lid-close or off-power still stops everything (clamshell+power+display is out of scope). Serve config persists across reboots.

## Rollout

- **Stage 0 (BLOCKED, prereq):** standard Tailscale installed + signed in on Mac and iPad via the supported route; ACL limiting access to the user's own devices.
- **Stage 1:** `launchd` for `tmux-dash`; confirm Serve reaches the board. *Human gate: open the MagicDNS URL on the iPad.*
- **Stage 2:** Host-allowlist change + tests. Outcome: iPad views the Overview over HTTPS, notifications fire.
- **Stage 3:** iPad UI (layout B, confirm A, full action surface, audit log).
- **Stage 4 (deferred):** live terminal over the tailnet (ttyd same-origin via Serve, CSP update, touch xterm).

## Acceptance

- **`board/tests/` Host allowlist:** a request with `TMUX_DASH_EXTRA_HOSTS=mac.example.ts.net` and `Host: mac.example.ts.net` returns 200; an unlisted Host returns 421; localhost entries still pass; the env var empty/unset leaves today's behaviour.
- **`board/tests/` actions + audit:** each confirm-gated action requires its flag/`confirm`; each iPad-triggered action writes an audit line with target and outcome and no token/secret.
- **No-CORS / header-token regression test:** `/api/action` without `X-Dash-Token` is rejected; no `Access-Control-Allow-Origin` is emitted.
- **Mobile layout:** the card list renders and is usable at iPad-mini widths (portrait and landscape); ordering matches the Overview; a destructive action shows the inline confirm with the target named and the Confirm control offset from the trigger.
- **Human gates after Stage 0 (cannot be settled by tests):** Serve reaches the board over the tailnet; the iPad page is a secure context and one real notification fires; an inline-confirm Stop over cellular stops the right agent and logs it; token rotation invalidates the old URL.

## Out of scope

- The live embedded terminal (Stage 4, separate design when reached).
- Any unmanaged/userspace Tailscale install, or exposing the board via Funnel or a public tunnel.
- An app login (seam left; not built in v1).
- Clamshell-mode reachability.
