# OpenRouter: setup for both demo applications

This document is for people running the **public demo software**. It is not a presenter script. The OpenRouter adapter performs one non-streaming JSON-Schema request per candidate; it does not silently retry billable calls or substitute prepared results.

## 1. Requirements

- Python 3.10 or newer; install this project with `python -m pip install -e .`.
- A valid key from [OpenRouter](https://openrouter.ai/settings/keys) and available account credits/limits.
- An exact **model ID** from the [model directory](https://openrouter.ai/models?fmt=cards&supported_parameters=structured_outputs). Choose a model/provider that supports `response_format: json_schema`; models and routing change over time.
- **Demo 1 live only:** Docker Desktop/Engine. This is mandatory because the model proposes Python source code.
- **Demo 2 live:** no Docker necessary; the proposed configuration is validated and applied only to trusted local training code.

## 2. Configure your environment — do not commit secrets

### macOS / Linux (bash or zsh)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# Prompts without echoing your key. Do not paste it into a chat or shared terminal log.
export OPENROUTER_API_KEY="$(python -c 'import getpass; print(getpass.getpass("OpenRouter API key: "))')"
export OPENROUTER_MODEL='provider/model-id'  # REPLACE with the exact ID you selected
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .

$secret = Read-Host "OpenRouter API key" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $env:OPENROUTER_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
$env:OPENROUTER_MODEL = "provider/model-id"  # REPLACE with your chosen ID
```

Values only live in the current shell session and subprocesses; they are not saved to a configuration file by this project. `.env.example` is documentation only and is **not automatically loaded**. Don't put real secrets in `.env.example` or commit a `.env` file.

You can optionally set:

```bash
export OPENROUTER_TIMEOUT_SECONDS=45   # Valid range: 3–180
export OPENROUTER_MAX_TOKENS=3500      # Valid range: 100–12000
export OPENROUTER_REQUIRE_ZDR=1        # Optional: require ZDR-eligible routing
```

On Windows PowerShell, use `$env:NAME = "value"` instead of `export`.

The client fixes the OpenRouter host at `https://openrouter.ai/api/v1` and forbids redirects. Requests include `provider.require_parameters=true`, `provider.data_collection="deny"`, and optional `provider.zdr=true`. These settings can **reduce endpoint availability**; see [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection). Privacy claims depend on OpenRouter/provider policies, not on this repository.

## 3. Validate the key and model

```bash
loopeng preflight
```

This uses `GET /key` and `GET /models` and reports whether the model advertises structured outputs. It does not make an inference request. Then explicitly choose to make **one billable probe**:

```bash
loopeng preflight --probe
```

The probe submits a tiny strict-schema request to `POST /chat/completions`. It proves only that this account/model/route returned a well-formed simple answer at that time; it does **not** prove the model can repair the program or optimize the experiment.

## 4. Demo 2: live research configuration search

```bash
loopeng rd --backend openrouter --mode governed --seed 2026 --max-attempts 3 --max-elapsed 120 --presentation
```

The model proposes a JSON object containing `feature_map`, `lr`, `l2`, and `epochs`. The orchestrator rejects unknown keys, nonfinite numbers, out-of-range values and unexpected types. Trusted Python code fits the classifier and evaluates validation F1; held-out data is accessed once *after* selection finishes. See [EXPERIMENTS.md](EXPERIMENTS.md) for limitations.

## 5. Demo 1: live software engineering loop (Docker mandatory)

Install and start [Docker](https://docs.docker.com/get-docker/), then:

```bash
docker version
docker pull python:3.12-slim
docker image inspect python:3.12-slim

# Confirm your local Docker path works with the prepared fixtures first:
loopeng se --backend offline --sandbox docker --mode governed --max-attempts 3 --live

# Only then attempt model-generated code:
loopeng se --backend openrouter --sandbox docker --mode governed --max-attempts 3 --max-elapsed 120 --presentation
```

For live source, the model proposes only `ledger.py`. The engine checks path, source size, AST shape and allowed top-level imports; stages a source file, writes its SHA-256 hash and a diff, and runs public checks first and separate acceptance checks only after public PASS. For runtime isolation it uses Docker with no network, a read-only filesystem and candidate mount, dropped capabilities, a non-root user and resource limits. **This is defense-in-depth, not a guarantee of safe execution of malicious Python.** Do not run on a privileged or sensitive host; prefer a disposable VM. See [SECURITY.md](../SECURITY.md).

## 6. Results, recovery and cost awareness

Every invocation writes its own `runs/<run-id>/` directory. `--presentation` prints simplified evidence statements and generates a local `report.html` without extra API calls; it can optionally open the report with `--open-report`. The original `--live` mode still produces raw event JSON. Run `loopeng report runs/<run-id>` to display the JSON summary or `loopeng report runs/<run-id> --html --open` to generate/open a self-contained visual evidence report. Use `--resume <run-id>` with the **same backend, seed (for research), mode, sandbox (for software), and outputs directory** for a staged/interrupted run. Resume does not guarantee exactly-once external model inference: a network timeout may have consumed credits even when no response was received.

The adapter does **not** automatically retry failed API requests. The orchestrator increments `api_calls` before sending each request, and a run stops after the configured attempt/API budget. Token usage and USD cost are included only when the provider reports them; values can be absent and should not be mistaken for a hard spending cap. Set a dedicated key limit/guardrail at OpenRouter.

Do not upload raw `runs/` directories to public GitHub without review: they may include generated source, prompts indirectly reflected in artifacts, and timing/model metadata. The repository's `.gitignore` excludes `runs/`.

## 7. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `Set OPENROUTER_MODEL and OPENROUTER_API_KEY` | Env not set in this shell | Set both variables in the terminal running the command |
| Preflight says model not listed | Incorrect/deprecated ID or account visibility | Copy the exact current model ID from OpenRouter directory |
| Model lacks structured outputs | Incompatible model/provider | Choose a model explicitly supporting JSON Schema; do not disable validation |
| HTTP 401/403 | Authentication, account or provider policy | Inspect OpenRouter account, permissions, ZDR and guardrails |
| HTTP 402 | Credits/billing | Add/enable allowed credits in OpenRouter account |
| HTTP 429 | Rate limits | Stop and retry manually later; one request may already be billable |
| HTTP 400 / unsupported parameters | Routing or schema support | Use a different endpoint/model supporting required parameters |
| `Docker CLI not installed` | Docker not available | Install/start Docker; use research demo until ready |
| `pull access denied` or missing image | Image absent | Run `docker pull python:3.12-slim` |
| `ESCALATED` | Model returned invalid policy/schema/code or API failed | Inspect `summary.json` and `events.jsonl`; no implicit fallback is performed |
| `BUDGET_EXHAUSTED` | Configured attempts/time/tokens limit | Treat as a bounded outcome, not proof of failure or convergence |

## API documentation

- [Chat Completions endpoint](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request)
- [Model discovery](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [Structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [Provider routing and privacy](https://openrouter.ai/docs/guides/routing/provider-selection)

**No real API inference or Docker daemon test was performed when this repository package was produced.** The OpenRouter integration has offline contract tests using simulated HTTP responses.
