# Changelog

## 1.1.0 — Evidence presentation

- Add optional `--presentation` terminal output: a concise, safe, human-readable view of the existing event stream.
- Add a self-contained offline HTML report for both demos (`--presentation`, `loopeng report --html`).
- Add `loopeng compare-se` for verified preauthored-candidate policy contrasts; reject mismatched/live samples.
- Add `--open-report` and `--open` for explicitly requested local browser opening.
- Add documentation, safe escaping and failure-path tests. Existing `--live` event output remains compatible.
- **No change** to source proposals, OpenRouter request schemas, acceptance rules, research data, metrics, budget logic or container execution.

## 1.0.0 — Initial public reference

- Two bounded offline/OpenRouter demos, journaled checkpoints, policy gates, Docker-only execution for model-supplied software and the foundational test suite.
