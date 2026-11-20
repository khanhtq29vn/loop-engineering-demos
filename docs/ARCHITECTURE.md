# Architecture & decision boundaries

```text
                               Host orchestrator (trusted code)
          ┌───────────────────────────────────────────────────────────┐
          │ Budget → Proposer → Policy/Schema Gate → Stage + SHA-256  │
          │             │                            │                │
          │             └───── checkpoint / journal ─┤                │
          │                                          ↓                │
          │                                  Executor + Evidence       │
          │                                          ↓                │
          │                                Independent Verifier       │
          │                                          ↓                │
          │                               Accept / Retry / Stop      │
          └───────────────────────────────────────────────────────────┘
```

**Model authority:** propose candidates only. It cannot change the system's acceptance criteria or execute arbitrary host operations. **Host authority:** schema enforcement, staging, verification, versioning, budgets and final decision.

## Demo 1 — acceptance after execution

- Contract: `reconcile_ledger(entries)` operates on decimal strings, aggregates exactly, ignores identical idempotent replays, and rejects conflicting IDs.
- Offline proposer: three **preauthored** source replacements from `fixtures.py`. No LLM reasoning takes place in this mode.
- Live proposer: OpenRouter chat completion returning `{ "path": "ledger.py", "source": "..." }` under a strict schema. Files other than `ledger.py` are forbidden.
- Policy gate: Python AST shape/import checks and size limit; **AST filtering is not a sandbox**.
- Executor: known fixtures can run in a trusted local process; **model-written source must use Docker**. A source hash recorded at staging is rechecked before executing, including on resume.
- Verifier: public input/output checks followed by acceptance checks. The host supplies only inputs to the candidate runner, not expected outputs or pass/fail policy; the host compares results afterward.
- Decisions: `single_pass` ends after one try; `feedback_only` accepts on public PASS; `governed` accepts only on public + acceptance PASS. All run under bounded attempts and time.

**Important nuance:** the acceptance checks are distributed with the public repository. They are *withheld from the proposer prompt and from the candidate runtime*, but are not secret from a reader of this codebase. This is not a secure hidden benchmark and not a formal proof of correctness.

## Demo 2 — bounded ML experimentation

- Synthetic, seeded dataset generated in Python standard library.
- Stratified split into training/validation/held-out sets. Preprocessing statistics come from training data only.
- Fixed optimizer: logistic regression using full-batch gradient updates. Proposed changes are restricted to `feature_map`, learning rate, L2 coefficient and epochs; model-generated executable code is never evaluated in this demo.
- At each attempt: train on training split, score on validation, `KEEP` only if strictly better than current best. This policy produces a nondecreasing **stored** best-so-far metric, not monotone candidate performance or proof of global convergence.
- Held-out evaluation is performed **once after selection**. Candidate prompts include prior validation results but not held-out metrics.
- Selection and evaluation use a single dataset/seed; no statistical claim about generalization across datasets or seeds follows.

## Operational invariants

1. **No trust escalation:** untrusted model output cannot edit verifier code, tests, budget or host policy.
2. **Acceptance tied to evidence:** candidate SHA-256 and verification outcome are recorded per attempt.
3. **Bounded attempts:** API call count recorded before submission; no implicit billable retry.
4. **Durable but not distributed:** `state.json` is atomically replaced; `events.jsonl` is append-only under a single-writer assumption. There is no cluster lease, distributed transaction or exactly-once delivery guarantee.
5. **No held-out leakage:** held-out results are computed only after research search ends.
6. **No fabricated results:** offline fixtures are labeled as prepared; live runs report the model and actual outcomes when the provider is available.

Check [SECURITY.md](../SECURITY.md) before executing source proposed by any model.
