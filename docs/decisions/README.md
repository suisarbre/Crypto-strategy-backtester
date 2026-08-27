# Architecture Decision Records

One file per decision, numbered, **append-only**. Never edit an accepted ADR to
reflect a change of mind — write a new one and mark the old `Superseded by ADR-00X`.

## Why these instead of more diagrams

The diagrams in `docs/images/` were written in the present tense about a system
that partly didn't exist yet, and had no mechanism to become true. An ADR is a
dated record of a moment — "on 2026-08-26 we decided X because Y" stays true
forever, even after X is ripped out.

## Format

```markdown
# ADR-00N: <decision in one line, active voice>

Date: YYYY-MM-DD
Status: Proposed | Accepted | Implemented | Superseded by ADR-00X

## Context
What forced the decision. Include the concrete symptom, not just the theory.

## Decision
What we chose. Present tense, specific enough to implement against.

## Consequences
What this costs, including what now breaks or gets harder.

## Open Questions   (only while Status: Proposed)
```

Keep it to roughly one screen. If your ADRs get long, the process is dying.

## When to write one

> Write an ADR when you'd otherwise re-litigate the decision at 2am.
> Skip it when there's one obvious right answer.

A bug with a single correct fix needs no ADR. A bug whose fix requires picking
between three defensible designs does — that's where the drift in this repo
actually came from.

## Index

| ADR | Status | Title |
|---|---|---|
| [001](ADR-001-strategy-identity.md) | Implemented | Strategy identity keys on filename stem |
| [002](ADR-002-execution-adapter.md) | Proposed | Order execution lives behind an ExecutionAdapter |
