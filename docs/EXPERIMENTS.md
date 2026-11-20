# Reproducibility & interpretation

## Protocol

This is an **instructional systems experiment**, not an evaluation of general LLM capabilities. Its purpose is to make the roles of the proposer, executor, verifier, state store and budget observable.

### Software Engineering

The immutable reference fixture sequence intentionally exhibits the following states:

| Attempt | Public input/output checks | Additional acceptance checks | Governed decision |
|---|---|---|---|
| 1 | FAIL | NOT RUN | Retry |
| 2 | PASS | FAIL | Retry |
| 3 | PASS | PASS | ACCEPTED |

- **Single-pass** demonstrates failure without feedback.
- **Feedback-only** accepts after public PASS at attempt 2, yet additional acceptance checks fail.
- **Governed** checks both suites and reaches candidate 3.

This establishes a counterexample for a **specific verification policy**, conditional on prepared candidates and the implemented checks. It does not quantify false acceptance in a natural distribution of tasks or prove that a governed system is universally superior.

### Scientific Research

The synthetic binary classification example uses a fixed seed `2026` and 720 generated observations. A logistic model compares linear, interaction and quadratic feature maps. The offline proposer returns five manually prepared configurations, not model-discovered hypotheses.

The script reports validation F1 for each configuration and retains strict best-so-far; held-out F1 is evaluated **once**, after all proposals have been considered. Default expected approximate values for seed 2026:

| Metric | Offline reference value |
|---|---:|
| Baseline validation F1 | 0.6309 |
| Best validation F1 | 0.8734 |
| Baseline held-out F1 | 0.6483 |
| Selected held-out F1 | 0.8828 |

The run ends as `SEARCH_COMPLETE` when the search budget expires, not because it mathematically converged. No claim is made about global optimality, significance, generalization or multiple-seed stability.

## Reproduce

```bash
python -m pip install -e .
loopeng se --backend offline --mode single_pass
loopeng se --backend offline --mode feedback_only
loopeng se --backend offline --mode governed
loopeng rd --backend offline --mode governed --seed 2026
python -m unittest discover -s tests -v
```

`runs/` contains new run IDs; report outcomes with `loopeng report runs/<run-id>`. Filenames and timestamps may differ, while deterministic reference scores and decisions should match when the environment and Python implementation are compatible. The implementation intentionally requires no GPU or ML framework.

## Research context — selected primary material

- Yao et al. (2023), [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629).
- Anthropic (2024), [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents).
- Anthropic, [Demystifying Evals for AI Agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents).
- AWS Builders' Library, [Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/).

These are conceptual sources; **none** are claimed to have validated the numerical results of this toy repository.
