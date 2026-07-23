# ADR 0002: Read-only SQL policy

- Status: Accepted
- Date: 2026-07-22

## Context

Generated SQL processes untrusted questions and uploaded datasets. Mutation, external scans, extension loading, and multi-statement execution would expand the blast radius beyond analysis of the materialized dataset.

## Decision

Allow one `SELECT` or `WITH` statement against the in-memory `dataset` table. Reject mutation, DDL, comments, multi-statements, external file functions, attachment, extension loading, and dangerous DuckDB commands before execution. Run `EXPLAIN` and cap returned rows.

## Consequences

- Analysis cannot alter storage or read arbitrary host files through SQL.
- Some legitimate DuckDB features remain unavailable by design.
- New SQL capabilities require an explicit policy update and regression tests.
