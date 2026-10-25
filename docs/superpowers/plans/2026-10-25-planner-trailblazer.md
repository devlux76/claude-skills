# Planner Trailblazer Assignment Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Claude reviews the integration and owns Trailblazer prerequisite changes.

**Goal:** Explicit planner assignment starts the local coding worker and records verified outcomes.

**Architecture:** Extend the existing Python planner, retaining its SQLite lock and git-bug mirror. A small assignment supervisor sends one durable VORTEX request, follows its case without model polling, and independently verifies its candidate.

**Tech Stack:** Python standard library, git-bug, existing VORTEX CLI and Trailblazer CLI.

**Spec:** ../specs/2026-10-25-planner-trailblazer.md

## Global Constraints

- Actor `trailblazer`; one active task; no automatic merges, pushes, or stale replay.
- Use the existing dedicated VORTEX resource gate; never call Runner.submit.
- Current operator commit rule: existing same-repository issue; whole message at most 255 characters including trailers.
- Temporary test fixtures and the live planner remain separate during development.

## Review Focus

- Repeated/concurrent assignments dispatch one task.
- Other actors' claims and completed issues cannot be stolen or revived.
- Shared or self-repair repositories cannot be guessed into execution.
- A forged candidate from another repository or a failed check cannot become done.
- Interrupted dispatch remains visible and never automatically repeats a side effect.

### Task 1: Assignment and supervision

**Files:** Modify `planner/scripts/planner.py`; create `planner/scripts/trailblazer_assignment.py`; extend `planner/scripts/test_planner.py`.

**Interfaces:** `planner assign REF trailblazer --check COMMAND [--file PATH] [--dispatch-config PATH]`; local dispatch configuration provides trusted CLI paths and the admitted VORTEX peer.

- [x] Add real temporary git-bug tests for ownership/idempotence, assignment-triggered work, failed checks, and self-repair rejection.
- [x] Run the new tests and observe missing assignment behavior fail.
- [x] Persist the assignment alongside the claim; launch one supervisor after the durable mirror.
- [x] Follow the admitted case, verify its commit in an isolated worktree, and record done or block through existing planner commands.
- [ ] Run `python3 planner/scripts/test_planner.py`; all existing and new tests pass.

### Task 2: Install and verify

**Files:** Update `planner/SKILL.md`; install the reviewed scripts and trusted local dispatch configuration.

- [x] Document explicit assignment, concrete repository cards, candidate review, and recovery.
- [x] Ask Claude for code review; address material findings.
- [ ] Verify the source issue exists; commit with its reference and a message under 160 characters.
- [ ] Install after tests and review; perform one bounded live assignment through the existing resource gate.
- [ ] Record observed result and remaining limitations on `shared:ee9a6d0` and `skills:ce60805`.

## Verification ledger

- Baseline: 7 tests passed.
- Assignment test failed on missing `assign`, then passed after implementation.
- Interrupted supervisor test failed (remained doing), then passed with model-free reconciliation.
- Explicit release/reassign test failed (reused request), then passed with retained attempt history.
- Claude reviewed all integration files and independently ran 14 tests. His same-repo concern was withdrawn because shared cards are refused.
- Claude found unbounded admission/result waits; two silence tests failed, then passed after one four-hour deadline was added. No remote case is cancelled or retried by expiry.
- Interface choice delegated by the operator: use explicit planner assignment; labels remain a mirror.
