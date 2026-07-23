# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.2.0] - 2026-07-22

### Added

- Auditable dashboard workspace with rendered SVG charts and trace timeline.
- Downloadable standalone HTML analysis reports.
- 100-case deterministic benchmark across seven evaluation categories.
- Adversarial Python sandbox regression tests.
- Branch coverage reporting with a 75% CI floor.
- Architecture decision records for planning, SQL, and sandbox boundaries.

### Changed

- Strengthened Python AST policy against private attributes, dynamic builtins, and arbitrary file readers.
- Expanded benchmark datasets and statistical reasoning cases.
- Reworked README and evaluation documentation around reproducible portfolio evidence.

### Fixed

- Preserved read-only dataset access for approved pandas CSV and Parquet calls while blocking file-I/O bypasses.
