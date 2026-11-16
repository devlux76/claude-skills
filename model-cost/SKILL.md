---
name: model-cost
description: Use when choosing which Claude model (Opus, Sonnet, Haiku, Fable) should get delegated or subagent work, or when asked whether a model is burning plan usage faster than expected - reports each model's measured cost against the 5-hour limit per token.
---

# model-cost

Anthropic's plan cost per token does not follow list prices; Opus is sometimes quietly discounted.
`model-cost-report` measures it: it fits hourly rises in the 5-hour % (usage-ledger) against each
model's tokens from all transcripts, subagents included.

- Run `model-cost-report` for the table and verdicts.
- It also runs as a SessionStart hook (startup, clear) with `--hook`: it refreshes (cached 10 min),
  rewrites memory `reference_model_cost_rates.md`, and injects the verdicts into user sessions
  (not background jobs).

Apply it: give work to the cheapest model that is good enough. A model that is not cheaper than Opus
per token gets no work Opus would do better. `[low data]` (fewer than 10 active hours) is a hint only.

Install: `ln -sf ~/.claude/skills/model-cost/model-cost-report ~/.local/bin/model-cost-report`.
The usage-ledger must also log SubagentStop (it reads `agent_transcript_path`), so subagent turns are counted.
