# ADR 0001: Deterministic-first planning

- Status: Accepted
- Date: 2026-07-22

## Context

Analysis plans affect generated SQL, evidence, and reported conclusions. A portfolio system needs reproducible behavior without requiring a model API key, while still allowing structured LLM planning as an optional extension.

## Decision

Use `PlanBuilder` as the default planner for supported intents. Keep `OpenAIPlanBuilder` opt-in, require structured output, validate referenced columns, and fall back to deterministic planning when model planning is unavailable or invalid.

## Consequences

- Local runs and benchmarks remain reproducible and offline-capable.
- Supported intents stay explicit and bounded.
- Open-ended language coverage requires new deterministic rules or validated model planning.
