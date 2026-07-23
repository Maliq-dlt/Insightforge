# Evaluation

## Portfolio benchmark

Benchmark records live in `benchmark/questions`. Each record defines dataset, question, expected value, selector, category, and difficulty. The suite contains 100 cases across:

- aggregation and segmentation;
- time-series comparison and root-cause decomposition;
- missing-value/data-quality checks;
- statistical reasoning;
- ambiguous questions;
- prompt-injection-shaped inputs.

Run locally:

```bash
uv run pytest tests/integration/test_benchmark.py -q
```

Run through API:

```bash
curl -X POST http://localhost:8000/api/v1/benchmarks/run
curl http://localhost:8000/api/v1/benchmarks/latest
```

The runner stores JSON output in `.runtime/benchmark/reports/latest.json` and checks answer accuracy, execution success, evidence coverage, read-only SQL validity, and reproducibility. See `docs/benchmark-results.md` for the verified snapshot and its limitations.

## Test coverage

Branch coverage has a 75% CI floor. Run the same gate locally:

```bash
uv run coverage run -m pytest
uv run coverage report
uv run coverage html
uv run coverage xml
```

Reports are written under `.runtime/coverage/`.

## Expansion path

The current suite is a deterministic regression gate for supported MVP intents. Portfolio-grade evaluation still needs independent datasets, paraphrase generation, larger sample sizes, adversarial SQL/Python policy cases, and model comparison. Do not treat the current score as a production quality estimate.
