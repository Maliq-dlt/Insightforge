# Evaluation

## Smoke benchmark

Benchmark records live in `benchmark/questions`. Each record defines dataset, question, expected value, tolerance, category, and difficulty.

Run via API:

```bash
curl -X POST http://localhost:8000/api/v1/benchmarks/run
```

The runner stores JSON output in `.runtime/benchmark/reports/latest.json`.

## Scores

- Numerical score: exact or tolerance-aware numeric comparison.
- Evidence coverage: fraction of executed evidence keys cited by final answer.
- SQL validity: read-only policy plus successful execution.
- Reproducibility: same dataset fingerprint and generated SQL produce same result.

## Expansion path

MVP target: 30 records across aggregation, filtering, statistical reasoning, root-cause, and data-quality categories. Portfolio target: 100–200 records, multiple datasets, adversarial cases, and model comparison.
