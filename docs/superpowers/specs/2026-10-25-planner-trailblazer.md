# Planner assignments for Trailblazer

The operator wants assigning an issue to Trailblazer to start its local coding
worker automatically, with planner access and durable progress, while paid
frontier agents are unavailable. The operator delegated interface choices to
Codex and Claude; both selected an explicit assignment command.

`planner assign REPO:BUG trailblazer --check COMMAND [--file PATH]` records one
durable assignment and performs a bounded admission handshake. It passes the
current card through Trailblazer's existing VORTEX admission and dedicated
resource gate, records the accepted case ID, and exits. Elixir/OTP owns all
execution supervision, independent verification, deadlines and recovery, and
records the final result through planner as actor `trailblazer`.

Assignments use a concrete repository card; a shared issue must be decomposed
into repository cards first. One active card per actor remains the rule.
Repeated assignment must not launch another task. Closed, verified, owned,
or Trailblazer-self-repair cards must not execute. A failed/interrupted worker
must block for explicit reconciliation. There is no timer that starts models.

A returned candidate must belong to the assigned repository, and its exact
commit must pass the explicit check in a separate worktree before planner done.
Completion records evidence and a candidate commit; nothing merges or pushes.
The worker carries the card context and updates planner through its supervisor;
the model does not receive arbitrary shell or planner ownership authority.
The Python transport handshake has a bounded client timeout. Elixir owns a
four-hour result backstop, a one-hour verification limit, and bounded planner
mirrors. Expiry blocks without retrying or cancelling a possibly running case.
The companion and task supervisor restart together; caller death terminates
check process groups, and interrupted verification worktrees are cleaned on
recovery. Pending durable mirrors are retried on companion restart. An explicitly
released, reconciled blocked assignment may be assigned afresh; history remains.
