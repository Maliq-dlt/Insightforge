# ADR 0003: Python sandbox boundary

- Status: Accepted
- Date: 2026-07-22

## Context

User-supplied Python can bypass application controls if executed in the API process. Static AST checks reduce obvious abuse but do not provide a complete isolation boundary.

## Decision

Validate code with a restrictive AST policy, allow only approved imports and dataset reads, block private/dunder access and dynamic builtins, then execute through a Docker runner with a read-only dataset mount, no network, resource limits, timeout, and output cap. Do not expose the host Docker socket to the API container in Compose.

## Consequences

- Local Python analysis requires Docker CLI and a running daemon.
- AST policy and container isolation provide layered controls, not a claim of perfect sandboxing.
- Multi-user production deployment needs a separate sandbox worker and tenant quotas.
