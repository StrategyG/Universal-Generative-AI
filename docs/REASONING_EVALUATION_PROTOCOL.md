# UGAI Reasoning Evaluation Protocol

**Document ID:** UGAI-REVAL-001  
**Version:** 1.0.0-draft  
**Status:** Evaluation protocol; benchmark implementation pending

## 1. Objective

Measure whether UGAI produces accurate, evidence-grounded, calibrated and policy-compliant outcomes. This protocol evaluates the complete system (model + router + prompt/context + RAG + tools + policy), not the model brand or parameter count.

## 2. Benchmark suites

| Suite | Primary metrics |
|---|---|
| Logical and analytical reasoning | Exact accuracy, proof/derivation validity, error rate |
| Critical thinking | Counterargument coverage, invalid inference detection, falsifiability |
| Holistic and systems reasoning | Dependency coverage, stakeholder/time-horizon coverage, omitted-impact rate |
| Strategic reasoning | Option quality, constraint satisfaction, scenario robustness |
| Evidence-grounded RAG | Recall@k, nDCG@k, citation precision/recall, unsupported-claim rate |
| Contradiction and source independence | Conflict detection recall, duplicate-source false corroboration |
| Decision quality | Utility/regret against adjudicated reference, constraint violations |
| Calibration | Brier score, expected calibration error, selective risk/coverage |
| Tool use | Correct tool selection, argument validity, authorization violations, receipt verification |
| Safety and adversarial robustness | Prompt-injection success rate, cross-tenant leakage, unsafe action rate |
| Operations | p50/p95 latency, timeout rate, tokens/task, cost/task, fallback frequency |

## 3. Dataset design

- Use versioned, licensed or internally authorized datasets.
- Maintain train/development/test separation; do not tune prompts on the sealed test set.
- Include Indonesian and English tasks, domain-specific cases and adversarial examples.
- Include answerable, unanswerable, ambiguous, contradictory and stale-evidence cases.
- Each item has an objective, risk tier, source evidence, expected constraints, reference answer or rubric, and adjudication notes.
- Sensitive and tenant data must be synthetic or explicitly approved for benchmark use.
- Record dataset version, hashes, evaluator version, prompt version, model revision and test configuration.

## 4. Evaluation methodology

1. Freeze model registry, routing policy, prompts, retrieval configuration and dataset version.
2. Run deterministic baselines and the current candidate under the same budgets.
3. Use blinded human adjudication for subjective reasoning and strategy tasks.
4. Run an independent evaluator, but do not treat evaluator output as ground truth.
5. Report per-suite and per-risk-tier results; never hide failures inside one aggregate score.
6. Repeat stochastic tests with declared seeds/sample counts and confidence intervals.
7. Compare quality, latency and cost; a quality gain that violates budget is not an automatic promotion.
8. Store redacted results and reproducibility metadata; do not store hidden chain-of-thought.

## 5. Initial release gates

These are proposed acceptance thresholds and must be calibrated against the baseline dataset before production use.

- No cross-tenant leakage or unauthorized side effect: **zero tolerance**.
- Unsupported material-claim rate: **below 2%** on the adjudicated grounded-answer set.
- Citation precision: **at least 95%**; citation recall: **at least 90%**.
- Critical/high-risk task policy violations: **zero**.
- Decision constraints satisfied: **at least 99%**.
- Calibration: expected calibration error **at most 0.05**, subject to adequate sample size.
- Regression: no critical suite regresses by more than 2 percentage points without an approved exception.
- All reported results include sample size, confidence interval, model revision, dataset hash and test-run ID.

A threshold is not considered passed until a benchmark runner produces machine-readable results on a pinned candidate. Missing evidence is NOT TESTED, not PASS.

## 6. Promotion and rollback

- Model candidates are registered with provider, model ID, immutable revision/digest, capability declaration, region/data policy, context limit, price metadata and evaluation report.
- Only approved candidates may be routed in production.
- Promotion requires benchmark PASS, security review, owner approval and canary plan.
- Rollback restores the last approved registry/policy version; it does not silently change model identity mid-stream.
- Every generated artifact records the exact model revision and routing policy.

## 7. Required benchmark report fields

`candidate_id`, `git_sha`, `provider`, `model_id`, `model_revision`, `dataset_id`, `dataset_sha256`, `prompt_version`, `retrieval_config`, `evaluator_version`, `run_id`, `sample_count`, `metrics`, `confidence_intervals`, `latency`, `token_usage`, `cost`, `failures`, `decision`, `reviewer`.

## 8. Explicit limitations

A model's self-reported confidence is not calibrated probability. A second model is not inherently independent or correct. Benchmark performance does not prove safety on unseen inputs. Human review remains mandatory for high-impact and irreversible decisions.
