"""Audience-facing terminal narration of *recorded* loop events.

This module performs no inference, changes no decision, and deliberately omits
candidate source, protected-test contents, prompts and provider responses.
"""
from __future__ import annotations

import math
import re
from typing import Any

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _safe(value: Any, limit: int = 72) -> str:
    """Untrusted model/metadata values must not control terminal rendering."""
    text = _CONTROL.sub(" ", str(value))
    # Explicitly neutralize terminal escape control sequences and their payloads.
    text = text.replace("\x1b", "")
    return text[:limit] + ("…" if len(text) > limit else "")


def _number(value: Any, places: int = 4) -> str:
    if isinstance(value, bool):
        return "n/a"
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return "n/a"
    return f"{n:.{places}f}" if math.isfinite(n) else "n/a"


def _attempt(data: dict) -> str:
    value = data.get("attempt", "?")
    return f"#{value:02d}" if isinstance(value, int) and value >= 0 else "#?"


def format_event(kind: str, data: dict[str, Any] | None = None) -> str | None:
    """Return one screen-reader-friendly, truthful line or None for irrelevant events."""
    d = data if isinstance(data, dict) else {}
    if kind == "RUN_CREATED":
        return f"START    | { _safe(d.get('demo', 'run')).upper()}  ·  policy={_safe(d.get('mode', 'unknown'))}"
    if kind == "BASELINE_VALIDATED":
        return f"BASELINE | validation F1 = {_number(d.get('validation_f1'))}"
    if kind == "MODEL_REQUEST_STARTED":
        return f"PROPOSE  | {_attempt(d)}  model request started (may incur a charge)"
    if kind == "MODEL_REQUEST_COMPLETED":
        tokens_in, tokens_out = d.get("input_tokens"), d.get("output_tokens")
        cost = d.get("cost_usd_reported")
        usage = f"tokens in/out={_safe(tokens_in,12)}/{_safe(tokens_out,12)}"
        charge = (f" · provider-reported USD {_number(cost, 5)}" if cost is not None else "")
        return f"MODEL    | {_attempt(d)}  {_safe(d.get('model', '?'),48)} · {usage}{charge}"
    if kind == "CANDIDATE_STAGED":
        return f"STAGE    | {_attempt(d)}  source candidate saved; verification follows"
    if kind == "HYPOTHESIS_STAGED":
        cfg = d.get("configuration") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        feature = _safe(cfg.get("feature_map", "?"), 28)
        return (f"STAGE    | {_attempt(d)}  feature={feature} · lr={_number(cfg.get('lr'), 5)}"
                f" · l2={_number(cfg.get('l2'), 5)} · epochs={_safe(cfg.get('epochs', '?'), 7)}")
    if kind == "VERIFIER_RESULT":
        public = "PASS" if d.get("public_passed") is True else "FAIL"
        protected = ("NOT RUN" if d.get("protected_passed") is None else
                     "PASS" if d.get("protected_passed") is True else "FAIL")
        return f"VERIFY   | {_attempt(d)}  public={public} · acceptance={protected}"
    if kind == "EXPERIMENT_EVALUATED":
        choice = "KEEP" if d.get("kept") is True else "REJECT"
        return (f"EVALUATE | {_attempt(d)}  candidate validation F1={_number((d.get('validation') or {}).get('f1'))}"
                f" · {choice} · best-so-far={_number(d.get('best_so_far_f1'))}")
    if kind == "HELDOUT_EVALUATED_ONCE":
        report = d.get("heldout_report") or {}
        if not isinstance(report, dict):
            report = {}
        baseline, selected = report.get("baseline") or {}, report.get("selected") or {}
        return (f"HELDOUT  | evaluated AFTER selection · baseline={_number(baseline.get('f1'))}"
                f" · selected={_number(selected.get('f1'))}")
    if kind == "RUN_TERMINAL":
        status = _safe(d.get("status", "?"), 35)
        return f"STOP     | {status} (a terminal status, not a convergence proof)"
    if kind == "PROPOSAL_REJECTED":
        return "GATE     | invalid or refused proposal; no candidate accepted"
    if kind == "POLICY_DENIED":
        return "GATE     | a requested operation was denied by policy"
    if kind == "RUN_RESUMED":
        return "RESUME   | previous checkpoint loaded"
    if kind == "STOP":
        return f"BUDGET   | stop reason={_safe(d.get('reason', '?'))}"
    if kind == "RUNTIME_FAILURE":
        return "EXECUTE  | execution failed; see run state for reason"
    return None
