---
name: cost-optimized-delegation
description: Use when delegating work through opencode serve and choosing which model/provider to run it on — the goal is to preserve scarce Claude credit by pushing grunt work onto the cheap delegation subscriptions.
---

# Cost-Optimized Delegation Strategy

## Overview

Delegation runs through our OpenCode server (assign over VORTEX; see **REQUIRED SUB-SKILL:** manage-opencode for monitoring and puppeting). This skill is about **which model to pick**.

**The scarce resource is Claude (you), not any delegation tier.** The user pays ~$20/mo for Claude and runs out of credit *several times a day* — they cannot afford the Claude Max program. The opencode/ollama subscriptions exist precisely so that build/run/diagnose/repair grunt work does NOT consume Claude credit. So: **delegate freely; the point is to keep Claude available for judgment.**

## Provider / Plan Map (corrected by the user 2026-10-02)

Connected and usable: **`opencode` (zen free)**, **`opencode-go`** (~$10/mo) and **`github-copilot`**.
There is **NO ollama plan** — `ollama-cloud/*` returns "not included in your free usage"; do not route
anything there. Never start a local `ollama`/`llama-server` either: it takes the GPU the user is working on.

| Model | Use | Caveats |
|---|---|---|
| `opencode/muse-spark-1.3-contributor-free` | **first choice** for delegated dev work | frequently unavailable; if a run errors at once, fall through |
| `opencode/mimo-v2.6-flash-free` | second choice; capable | **tends to run amok** — it will start services, restart things, widen scope. Give it a closed list of files it may touch, an explicit "do not start, stop or install anything; do not run servers; do not ask the user anything" clause, and review its whole diff |
| `opencode-go/*`, `github-copilot/*` | only when the user asks | `opencode-go` Muse Spark needs a privacy setting allowed; `opencode-go` minimax bills 3x |
| any `deepseek-*-flash`, `opencode/big-pickle` for dev | never | |

The other zen-free models are not worth using for code.

## Core Rule

1. **If the user names a model, use that model.**
2. **Otherwise: Muse Spark free, then MiMo 2.6 flash free.** If both fail, stop and tell the user rather
   than trying paid routes or local models.
3. **Never spend Claude on grunt work** the delegation models can do. Reserve Claude for judgment,
   design, steering, and verification — and verify every delegated result yourself.

## Claude Code subagents vs opencode

When the Claude session/weekly usage is high, prefer opencode over Claude subagents (Sonnet included) for work that is fully specified: pipeline runs, builds, mechanical edits, asset processing. Claude subagents draw on the same Claude usage window; opencode does not. Keep Claude subagents for work that needs browser/MCP tools opencode lacks or judgement mid-task.

## When NOT to Delegate (do it yourself)

- Single high-value decision or architectural trade-off → your judgment
- Novel research / original thinking
- Security-critical code
- Verifying delegated work is correct — **always yours**

## Quick Reference

```bash
OC="python3 ~/.claude/skills/manage-opencode/oc.py"
$OC new --dir REPO --model opencode/beam-free "task..."   # server default model (opencode.jsonc "model")
python3 ~/.claude/skills/manage-opencode/oc.py sessions     # models in use; full list: GET /api/model
# NEVER: ollama-cloud/* (no plan), local ollama/llama-server (GPU), deepseek-*-flash
```
