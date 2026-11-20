# Security model

This is an educational research demo. **It is not a hardened, production-grade untrusted-code execution platform.** It must not run untrusted Python on a host with sensitive secrets or privileges.

## Threat boundaries

- The **host** holds `OPENROUTER_API_KEY`. Candidate containers are created with no `-e` key injection and `--network=none`.
- Online source proposals are allowed only for `ledger.py`; a small AST/size/path gate rejects disallowed top-level structures. This is a policy check, not an arbitrary-Python sandbox.
- Online software verification requires Docker: non-root UID, no network, readonly root filesystem and source mount, no-new-privileges, dropped capabilities, memory/pid/CPU limits and per-suite timeout.
- Sandbox escape, daemon bugs, kernel compromise and resource exhaustion beyond these controls are **not excluded**. Prefer a disposable VM, not a personal/work machine holding secrets. Docker's isolation is defense-in-depth.
- The verifier's expected results and PASS/FAIL logic are held on the host; only test inputs are sent to the candidate process.
- **Public repo caveat:** the acceptance vectors are readable in the public source. They are withheld from prompt/container, not cryptographically secret. A model trained on or given the repository might already know them. This is not a private benchmark.
- Run artifacts include generated source and model metadata. `runs/` is ignored by Git. Review contents before sharing with third parties.

## OpenRouter and spend controls

- No API key is hardcoded, echoed in errors, or saved to a run artifact.
- OpenRouter requests disable redirects, fix the HTTPS host and request schema-compatible providers. The client never retries automatically after a timeout or provider error.
- One request can still be billable when it times out; recorded costs are provider-reported and may be missing. Configure a dedicated key spending limit in OpenRouter.
- `data_collection: deny` and opt-in `zdr: true` are routing policies, not a blanket guarantee about retention outside the provider or your own local logs.

## Operational expectations

1. Run offline tests first.
2. Use an independent, disposable environment for live software proposals.
3. Verify Docker daemon privileges, image source and isolation on your platform.
4. Do not report public or acceptance test PASS as universal correctness.
5. Do not report validation F1 improvements as proof of convergence/generalization.
6. Never publish raw API credentials, environment dumps or private run logs.

For issues affecting public sample code, open a GitHub issue **without secrets or exploit payloads that could harm others**. For security-sensitive reports, use a private contact method configured by the actual repository owner before publication.
