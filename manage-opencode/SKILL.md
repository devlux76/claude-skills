---
name: manage-opencode
description: Use when checking on, steering or inspecting OpenCode (our fork, OpenCode 2.x on 127.0.0.1:4096) - a periodic health check of work assigned to it over VORTEX, a run that is stuck, silent, grinding, out of quota or waiting on a form/permission, reading what a session did, interrupting it, or when the OpenCode server or its daily fork update looks broken.
---

# Manage OpenCode

OpenCode is our own fork (`~/vendor/opencode`, branch `local`), an OpenCode 2.x server on `127.0.0.1:4096` run by the user unit `opencode.service`. Work is assigned to it over VORTEX; this skill is how Claude and Codex watch it and occasionally puppet it. It is not as capable as a frontier model: never presume it did something, check.

`OC="python3 ~/.claude/skills/manage-opencode/oc.py"`, run `$OC -h` for every command.

## Rules

- **Assign over VORTEX, not with this tool.** One task = one brief file in the handoff dir + a conference + a DM naming the brief path and the worktree. `$OC new` is for puppeting and experiments only.
- **One OpenCode session at a time, ever** (free service; parallel use risks a ban). `$OC status` before starting anything. This includes OpenCode's own subagents: briefs must say "subagents one at a time, never in parallel"; never ask it to fan out. More than one RUNNING session in `$OC status` = steer the parent to serialize at once.
- **Record the assignment** on dispatch, or the monitor reads idle as healthy: `~/.local/share/claude-handoff/opencode-assignment.json` = `{"task", "conference", "brief", "worktree", "dispatched": <epoch s>, "done": false}`; `"done": true` when its report is accepted, `"parked": "<why>"` while on hold.
- **Check every 15-30 min** while work is in flight (a session cron job runs `$OC monitor`; cron jobs die with the session, so re-create it) and after every report. Exit 0 = fine, 20 = attention.
- **Verify every report**: the commit exists, read the diff, rerun at least the focused tests (the full suite for new code).
- Claude and Codex may ack or clear events in OpenCode's VORTEX mailbox (`~/projects/trailblazer/.vortex/opencode`); never each other's.

## Interventions

| `$OC monitor` says | Do |
|---|---|
| pending form / permission | `$OC forms` then `$OC answer SID FORM field=value`; `$OC permissions` then `$OC allow SID REQ` or `$OC deny SID REQ "why"`. A session waiting on one still shows as running. |
| believes in hidden tests / a grader | `$OC interrupt SID`, then post over VORTEX: no hidden tests; it designs the API and writes the tests |
| whole-disk search, git stash/push/merge, service restart | interrupt; undo any damage; post the exact repo/worktree it may touch |
| running but no new message past the stall window, or the same command repeated | `$OC show SID`, then interrupt + steer with the concrete next step |
| assignment open but nothing running | `$OC show SID` (it may have drifted to an older task); re-steer with ONE explicit task, or mark done |
| quota / rate limit | it is out of free usage: queue the work, never absorb it |

Steering: `$OC say SID "..."` queues after the current turn; `--steer` injects into the running turn. Prefer steering over VORTEX so the record stays in the conference.

## The fork and its update

- Daily at 04:30, `opencode-update.timer` syncs the GitHub fork's `dev` from upstream, merges `upstream/dev` into `local`, tests our patches, builds, smoke-tests, installs a release and restarts the server once nothing is running. `$OC update` shows the last result; details in `~/vendor/opencode/local/README.md`, log `~/.local/state/opencode-local/update.log`.
- A failed update leaves the running release untouched. Merge conflict: resolve on `local` in `~/vendor/opencode`, commit, `opencode-update --build-only`. Bad release: `opencode-update --rollback`.
- Every change to our fork gets a test listed in `local/tests.txt`.
- Auth: none. The server binds 127.0.0.1 only and runs with `OPENCODE_SERVER_AUTH=disabled` (`~/.config/opencode-local/server.env`, our patch). If a password is ever set there, `oc.py` sends it. Logs: `journalctl --user -u opencode`.

## 2.x API notes (when `oc.py` lacks something)

Routes are under `/api` (live list: `~/vendor/opencode/packages/protocol/openapi.json`). Sessions: `GET/POST /api/session` (`location.directory`), `GET /api/session/active` (running sessions only), `GET /api/session/{id}/message` (newest first; assistant `content` parts: `text`, `reasoning`, `tool` with `state.input`), `POST .../prompt` `{text, delivery: queue|steer}`, `POST .../interrupt`, `GET .../form|permission`, events `GET /api/event` (SSE `data: {"type": ...}`; `session.execution.*`, `session.idle`). Never call a synchronous endpoint and wait on it: a run waiting on a form never finishes.
