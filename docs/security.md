# Security

## Trust boundaries

Uploaded files, column names, cell values, questions, and optional LLM output are untrusted. Dataset text never becomes an instruction. The structured LLM adapter receives schema and profile summary, validates required columns, and validates every generated query with the read-only SQL policy.

## SQL policy

Only one `SELECT` or `WITH` statement is allowed. Blocked operations include mutation, DDL, extension loading, attachment, external scans, comments, and multi-statements. The executor materializes the input dataset into an in-memory table named `dataset`; generated queries cannot choose source paths.

## Python sandbox

Python requests pass an AST policy before execution. The Docker runner uses a read-only image and dataset mount, `--network none`, CPU and memory caps, PID limits, timeout, output cap, and an import allowlist. Python output and code are recorded in the trace.

The API container does not receive a Docker socket in Compose. Do not mount a host Docker socket casually; use a separate sandbox runner for production multi-user deployments.

## Storage and access

Files stay under configured dataset and artifact directories. Uploads are streamed and capped. Dataset fingerprints support deduplication. Optional RBAC uses scrypt password hashes, hashed bearer tokens, expiry, and viewer/analyst/admin permissions. Do not send files to cloud models without explicit consent.

## Remaining hardening

- Replace SQLite trace and auth storage with PostgreSQL for multi-instance deployment.
- Add separate sandbox worker isolation and tenant-level quotas.
- Add OpenTelemetry export and secret-leakage regression cases.
- Review dependency and container image CVEs before production release.
