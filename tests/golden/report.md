# Model regression check: REGRESSION

Suite s. Baseline baseline vs candidate candidate. 20 of 20 cases paired, 0 missing.

- ok regressed: p = 0.003906 is below alpha 0.05 and the effect 0.45 reaches min_effect 0.05
- sim regressed: p = 0.01562 is below alpha 0.05 and the effect 0.1474 reaches min_effect 0.0; 1 of 20 paired case(s) have no usable score (baseline 0, candidate 1): c01

## Metrics

| Metric | Kind | Baseline | Candidate | Delta | 95% CI | p | Worse/better | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ok | pass_fail | 1.000 | 0.550 | -0.450 | [-0.650, -0.250] | 0.0039 | 9/0 | **REGRESSION** |
| sim | score | 0.900 | 0.753 | -0.147 | [-0.232, -0.063] | 0.0156 | 7/0 | **REGRESSION** |

- ok: p = 0.003906 is below alpha 0.05 and the effect 0.45 reaches min_effect 0.05
- sim: p = 0.01562 is below alpha 0.05 and the effect 0.1474 reaches min_effect 0.0; 1 of 20 paired case(s) have no usable score (baseline 0, candidate 1): c01

## Slices by tag

Exploratory. The p (Holm) column is corrected for the number of slices tested per metric and is the one the slice verdict uses.

| Tag | Metric | n | Baseline | Candidate | Delta | 95% CI | p | p (Holm) | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a | ok | 10 | 1.000 | 0.200 | -0.800 | [-1.000, -0.500] | 0.0078 | 0.0156 | REGRESSION |
| b | ok | 10 | 1.000 | 0.900 | -0.100 | [-0.300, +0.000] | 1.0000 | 1.0000 | INCONCLUSIVE |
| a | sim | 9 | 0.900 | 0.589 | -0.311 | [-0.400, -0.178] | 0.0156 | 0.0312 | REGRESSION |
| b | sim | 10 | 0.900 | 0.900 | +0.000 | [+0.000, +0.000] | 1.0000 | 1.0000 | NO_CHANGE |

## Newly failing cases (9)

| Case | Metric | Expected | Baseline output | Candidate output |
| --- | --- | --- | --- | --- |
| c00 | ok | a0 | answer 0 | wrong 0 |
| c01 | ok | a1 | answer 1 | ERROR: boom |
| c02 | ok | a2 | answer 2 | wrong 2 |
| c03 | ok | a3 | answer 3 | wrong 3 |
| c04 | ok | a4 | answer 4 | wrong 4 |
| c05 | ok | a5 | answer 5 | wrong 5 |
| c06 | ok | a6 | answer 6 | wrong 6 |
| c07 | ok | a7 | answer 7 | wrong 7 |
| c12 | ok | a12 | answer 12 | wrong 12 |

## Newly passing cases (0)

None.

## Still failing cases (0)

None.

## Flaky cases (1)

Passed and failed within one run, so the majority result was used.

| Case | Metric | Run | Pass rate |
| --- | --- | --- | --- |
| c12 | ok | candidate | 0.50 |

## Errors (2)

| Run | Case | Repeat | Error |
| --- | --- | --- | --- |
| candidate | c01 | 0 | boom |
| candidate | c01 | 1 | boom |

## Latency and cost

- Latency p50: 100.0 ms to 120.0 ms (+20.0%)
- Latency p95: 100.0 ms to 120.0 ms (+20.0%)
- Total cost: $0.2000 to $0.2200 (+10.0%)

## Settings

- alpha 0.05, bootstrap samples 300, seed 1, fail_on `regression`
- min_effect: default 0.05 for pass_fail metrics
- Tests: McNemar exact (pass_fail), sign-flip permutation (score), percentile bootstrap CI, Holm across slices.
