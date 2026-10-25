# Planner Trailblazer Assignment Implementation Plan

**Goal:** Explicit planner assignment starts the local coding worker and records independently verified outcomes.

**Architecture:** Python retains durable claims and git-bug mirrors, performs bounded VORTEX admission and exits. The admitted Elixir case association is durable before acceptance. An OTP one-for-all group owns the planner companion and verification tasks; existing Loop.Check owns check process groups and cancellation. No model replay, automatic merge or push.

**Spec:** ../specs/2026-10-25-planner-trailblazer.md

## Constraints

- Actor `trailblazer`; one active card; concrete admitted repository/check pairs only.
- Existing dedicated VORTEX resource gate; no Runner.submit or Trailblazer self-repair.
- Existing same-repository issue required for each commit; entire message <=255 characters.
- Bounded transport admission; Elixir result backstop and bounded verification/mirrors.
- Explicit reconciliation before retry, and prior case must be confirmed closed.

## Implementation and verification

- [x] Durable assignment, ownership and duplicate/concurrent dispatch tests.
- [x] Bounded Python admission client with Elixir planner/deadline metadata; no Python lifetime watcher.
- [x] Durable Elixir association, closed-case verification and done/block mirrors.
- [x] One-for-all supervision, process-group cancellation, bounded mirrors and interrupted-worktree cleanup.
- [x] Reproduce and fix companion recovery failures; 11 focused Elixir tests passed.
- [x] Local coding trial produced candidate d77b848; independently verified with 17 passing tests. Candidate not merged; concurrency test adapted into current tests.
- [x] Full corrected Python and Elixir suites, source review and skill validation.
- [x] Commit verified source issues skills:ce60805 and trailblazer:a6c0982.
- [x] Install corrected CLI and rebuild/restart idle Trailblazer service.
- [x] Verify live OTP tree and completion/recovery with real planner CLI.
- [x] Record evidence and operational handoff on shared:ee9a6d0.

## Review and recovery

Claude reviewed the initial integration and supplied Elixir companion 630331c, then became unavailable due authentication failure. Codex owns the final supervision correction and verification. Do not wait for a frontier agent. Review exact candidate commits before integration. Producer interruption before admission and complete lease/generation lifecycle remain shared:40dbd63; automatic integration remains trailblazer:1beebca.

## Final verification and installed state

- Source: planner correction 2bc587c; Trailblazer correction 1c86b5f.
- Full isolated Elixir suite: 634 passed, 4 excluded live/integration tests.
- Focused recovery suite: 11 passed. Installed Python planner: 21 passed.
- Skill validation and diff checks passed; production release compiled with warnings as errors.
- Idle Trailblazer rebuilt/restarted; live planner group and both children verified.
- Production crash smoke: companion death restarted both children, killed the old BEAM verification task and its OS check process, and left the group alive.
- Hermetic BEAM-to-real-installed-CLI smoke independently checked the exact candidate, recovered a failed mirror after companion death, preserved quoted evidence, avoided duplicate evidence, and removed its verification worktree.
- Earlier local coding trial proved the actual worker path. The corrected supervision path was verified without another costly coding-model run; its live admission/coding cycle has not been repeated.
- Both live source trees clean; no pushes or automatic candidate merges.
