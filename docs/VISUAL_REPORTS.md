# Visual evidence reports

**Public user guide.** These commands make the outcomes of the two runnable experiments easier to inspect. They do not change any model requests, execution policies, scoring rules or stored decisions.

## Terminal: raw vs readable

- `--live` retains the original machine-oriented `[LOOP] EVENT {JSON}` stream.
- `--presentation` prints short, selected evidence events (`PROPOSE`, `STAGE`, `VERIFY`, `EVALUATE`, `HELDOUT`, `STOP`). It also writes `runs/<run-id>/report.html` after the run.
- `--open-report` opens the generated HTML file after completion in your default browser; this is optional and should only be used on a machine with a desktop browser.

```bash
loopeng rd --backend openrouter --mode governed --max-attempts 3 --presentation
loopeng se --backend offline --mode governed --presentation
```

A model request can still time out, fail or consume credits. `--presentation` does not add inference requests or retries. If a run terminates in `ESCALATED`, `BUDGET_EXHAUSTED` or another non-success status, the visual report shows that status rather than presenting it as success.

## Offline HTML reports from saved runs

```bash
loopeng report runs/<run-id> --html
loopeng report runs/<run-id> --html --open
```

This reads `summary.json` and writes only `report.html` inside the same run folder. No credentials, Docker, network or model are used. The page has no JavaScript or external assets, is printable, and can be opened with a browser directly from disk.

**Demo 1:** The report shows the outcome of each staged candidate separately on public and acceptance checks. `NOT RUN` is different from `FAIL`. `ACCEPTED` is a policy outcome for the finite implemented checks, not proof of universal correctness.

**Demo 2:** The graph always starts at the recorded baseline, plots candidate validation F1 and best-so-far validation F1 as **different series on a 0–1 y-axis**, and shows held-out measurements separately. `SEARCH_COMPLETE` means a finite search ended; it does not mean mathematical convergence. A single seed/held-out score is not a statistically established generalization gain.

The provenance label is explicit: `LIVE MODEL PROPOSALS` or `PREAUTHORED OFFLINE CANDIDATES`. If the summary does not specify one, the page says `UNSPECIFIED PROPOSAL SOURCE` and makes no inference. The data in a run folder are **not a cryptographic proof of provenance**.

## Compare the two software acceptance policies

```bash
loopeng se --backend offline --mode feedback_only
loopeng se --backend offline --mode governed

# Replace with the actual two paths shown by your terminal:
loopeng compare-se runs/<feedback-run-id> runs/<governed-run-id> --open
```

This writes `comparison.html` inside the first run folder. The two runs must share the same prefix of *prepared* candidate SHA-256 fingerprints and public/acceptance outcomes. Comparison fails closed for model-generated proposals, mixed experiments, or mismatched records. It illustrates the effect of the **acceptance policy on one prepared counterexample**. It is not a benchmark of models or independent statistical trials.

## What gets published and what does not

The GitHub repository includes **code that generates reports**, not the live outputs, model-generated code, private credentials, model messages, or individual webinar speaker notes. `runs/` is ignored by Git. To share results outside your machine, deliberately review the local HTML or `summary.json` first.

## If the browser does not open

Open the printed file path manually in Finder/Explorer. The optional `--open` / `--open-report` flags ask the operating system to open the generated local `file://` URI; they do not host a web server. Avoid opening a report obtained from an untrusted third party unless you trust its provenance.
