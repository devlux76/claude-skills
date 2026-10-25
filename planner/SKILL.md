---
name: planner
description: Plan and track local AI work with the planner command over git-bug. Use for task selection, assignments, kanban status, claims, checkpoints, blockers, and resuming after compaction.
---

# Planner

Use `planner` from any directory. It returns compact JSON and uses the repositories listed in `~/.config/bug-watch/repos`. Board and tracking commands call no model; explicit `assign` starts Trailblazer's local coding worker. References are `vortex:6ee260f`, `opencode:b7fe55b`, or `shared:40dbd63`. Use a stable actor name (`glm`, `codex`, `trailblazer`), never a session ID.

```sh
planner --actor glm resume
planner board --repo vortex --column todo --limit 8
planner show vortex:6ee260f
planner --actor glm start vortex:6ee260f --plan 'Shorten wake envelopes; verify room and sender boundaries; measure size.'
planner --actor glm note vortex:6ee260f 'Intent: change the notice text; no mail or service state changes.'
planner --actor glm note vortex:6ee260f 'Result: focused tests passed; next: size comparison.'
planner --actor glm block vortex:6ee260f 'Provider quota exhausted; no retries until operator resumes.'
planner --actor glm start vortex:6ee260f --plan 'Resume from the recorded checkpoint.'
planner --actor glm done vortex:6ee260f --evidence 'Actual commands, results, commit, and remaining limits.'
planner --actor glm release vortex:6ee260f 'Explicit handoff reason; next action.'
planner add vortex --title 'Concrete task title' --plan 'Outcome and acceptance check' --priority p2
```

Local planning: Qwen prioritizes unclaimed todo cards labelled `dispatch:ready`; only Trailblazer is dispatched. Mark a card ready with `git -C <repo> bug bug label <bug-id> dispatch:ready`. The system wakes on changes or completion with no timer, no paid fallback, and no automatic merge. Verify with `python3 planner/scripts/test_planner.py`.

For well-specified coding work, use `planner assign <repo:bug> trailblazer
--check '<project check>' [--file relative/path]`. Pick a current, ready card
with a bounded requested change. Assignment starts the local worker through
its existing VORTEX resource gate; adding an owner label alone does not launch
work. Shared issues need a concrete repository part card first.

The actor is `trailblazer`. The Python client claims the card, sends its current
context and optional deadline, records acceptance/case ID, and exits. It starts
no watcher. Trailblazer's Elixir companion owns execution supervision, planner
updates, independent verification, deadlines and restart recovery under OTP.
It checks the exact candidate commit in a separate worktree before `done`; a
candidate is never merged or pushed automatically. Repeating `assign` returns
the same assignment without dispatching again. Use `--deadline-seconds N` to
change Elixir's default four-hour result backstop; expiry blocks without
retrying or cancelling a possibly running case. The client only has a bounded
transport admission timeout, which blocks an unconfirmed request.
After confirming the old case has stopped, explicitly `release` its card as
actor `trailblazer`, then `assign` again for a fresh attempt; earlier assignment
identities remain in the local record. Repeating `assign` without release never
retries a blocked job, and a released card cannot be reassigned while its prior
case is still open. An unconfirmed admission needs explicit reconciliation.
Only repository/check pairs admitted by the local dispatch configuration may
run; Trailblazer self-repair remains forbidden.

Start with `resume` after compaction. Read one card before acting. Use `git -C <repo> bug bug show <id>` if the bounded card omits needed detail. Work on one active card per actor; block or release it before taking another. A blocker retains task ownership but frees the actor for other work. Select ready work within the operator's authorized scope; priority alone is not permission to revive parked work.

Record intent before consequential effects and the observed result afterwards. Include what remains so another session can continue. `done` records verified work; it does **not** close the issue or grant permission to merge, deploy or spend money. Review/closure is separate and need not wait for an unavailable frontier agent.

Git-bug is the durable plan and progress record. Local SQLite claims serialize workers using this helper and survive compaction. Other tools can edit labels, so claims do not enforce all external workers. Claims never expire or automatically transfer. A stale owner requires explicit reconciliation; use its stable actor to release only after confirming it stopped. This helper is not the full lease/generation/reconciliation system tracked by `shared:40dbd63`.

On a write error, inspect `resume` and the issue before repeating a side effect. `planner --actor glm sync <ref>` repairs an interrupted issue mirror without changing the claim or duplicating its comment. Never infer completion from a mail acknowledgement. Keep session IDs, credentials and private runtime paths out of issue text. Check the board on task boundaries or actual notices; do not run a model polling loop. Automatic VORTEX wakes remain quota-held until the operator resumes them.

For service checks, candidate review and restart recovery, read
[the operations handoff](references/operations.md).
