# Benchmark results

Verified locally on **July 22, 2026** with the deterministic planner and DuckDB execution path.

Command:

```bash
uv run pytest tests/integration/test_benchmark.py -q
```

## Snapshot

| Metric | Result |
| --- | ---: |
| Cases | 100 |
| Passed | 100/100 |
| Numerical accuracy | 78/78 |
| Evidence coverage | 100% across 86 analysis cases |
| Read-only SQL validity | 86/86 |
| Reproducibility | 86/86 |
| Median local latency | 182.5 ms |
| Branch test coverage | 76% |

Coverage spans aggregation, segmentation, time-series comparison, data quality, statistical reasoning, ambiguous questions, and prompt-injection-shaped inputs. The full Python test suite passed 15 tests with a configured 75% coverage floor.

## Interpretation

This is a deterministic regression benchmark for supported MVP intents. It proves execution, evidence, SQL policy, and reproducibility for these records; it does not claim generalization to unseen datasets or open-ended analyst questions. Expand with independent datasets and model comparisons before treating the score as a production quality estimate.

Runtime JSON is written to `.runtime/benchmark/reports/latest.json`. The API exposes the latest report at `GET /api/v1/benchmarks/latest`.
