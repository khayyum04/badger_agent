---
name: start-phase
description: Start a fresh session on one phase of the context-management plan — loads the plan's context and follows its session protocol before any work begins
---

# Start Phase

Usage: `/start-phase N`, where N is the phase number (0–5). Run it at the start of a fresh session.

## 1. Find the phase

Read `starter/plan_docs/context_management/phases/0N-*.md` for the given N. If N is missing, is
not 0–5, or no such file exists, stop and ask which phase. Reading that file is what loads
`starter/plan_docs/context_management/CLAUDE.md` and its imports (roadmap, decisions, handoff
ledger, agent notes) — the plan's context does not load at launch.

## 2. Follow the plan's own protocol

Do "Starting a session" in `starter/plan_docs/context_management/CLAUDE.md` exactly as written
there: state the phase and its roadmap status, decide refine vs. implement, read the cited design
sections and the agent source, and report what you will reuse. Take the issue number from the
roadmap table.

Don't restate or shorten that protocol here; it lives in one place so it can't drift.

## 3. Stop and wait

End with the reuse report and wait for the user to confirm before writing anything. In a refine
session, ask one question at a time.
