"""Bounded, single-writer execution journal and durable checkpoints.

The reference intentionally does not implement distributed leases, exactly-once
external requests, or hard realtime enforcement of the total run budget.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid


TERMINAL_STATUSES = frozenset({
    "ACCEPTED", "BUDGET_EXHAUSTED", "ABORTED", "EXECUTION_FAILURE",
    "ESCALATED", "SEARCH_COMPLETE", "SINGLE_PASS_COMPLETE",
})


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Durably replace a JSON file using a same-directory temporary file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    # Directory fsync where supported; best-effort on other platforms.
    try:
        descriptor = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


@dataclass(frozen=True)
class Budget:
    max_attempts: int = 5
    max_elapsed_seconds: float = 90.0
    max_api_calls: int = 5
    max_recorded_tokens: int = 30000

    def __post_init__(self) -> None:
        if min(self.max_attempts, self.max_api_calls, self.max_recorded_tokens) < 1:
            raise ValueError("All count limits must be positive")
        if self.max_elapsed_seconds <= 0:
            raise ValueError("Elapsed-time limit must be positive")

    def exhausted(self, state: dict) -> str | None:
        """Check soft, between-attempt limits; not an OS process deadline."""
        if state["attempts_used"] >= self.max_attempts:
            return "max_attempts"
        if state["elapsed_seconds"] >= self.max_elapsed_seconds:
            return "max_elapsed_seconds"
        if state["api_calls"] >= self.max_api_calls:
            return "max_api_calls"
        if state["tokens_used"] >= self.max_recorded_tokens:
            return "max_recorded_tokens"
        return None


class RunStore:
    """Checkpoint and append-only journal owned by one process per run ID."""

    def __init__(self, root: Path, run_id: str):
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        if not run_id or any(character not in allowed for character in run_id):
            raise ValueError("Invalid run identifier")
        self.directory = Path(root).resolve() / run_id
        self.path = self.directory / "state.json"
        self.events_path = self.directory / "events.jsonl"
        self.directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def new(
        cls, root: Path, demo: str, mode: str, budget: Budget, details: dict | None = None
    ) -> tuple["RunStore", dict]:
        store = cls(root, f"{demo}-{uuid.uuid4().hex[:12]}")
        state = {
            "schema_version": 1,
            "run_id": store.directory.name,
            "demo": demo,
            "mode": mode,
            "created_at_utc": utcnow(),
            "status": "RUNNING",
            "phase": "IDLE",
            "attempts_used": 0,
            "api_calls": 0,
            "tokens_used": 0,
            "elapsed_seconds": 0.0,
            "budget": asdict(budget),
            "attempt_history": [],
            "current_candidate": None,
            "best_candidate": None,
            "details": details or {},
        }
        store.save(state)
        store.event("RUN_CREATED", {"demo": demo, "mode": mode})
        return store, state

    def load(self) -> dict:
        if not self.path.is_file():
            raise FileNotFoundError(f"No checkpoint at {self.path}")
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> None:
        state["last_checkpoint_utc"] = utcnow()
        write_json_atomic(self.path, state)

    def event(self, kind: str, data: dict | None = None) -> None:
        entry = {"time_utc": utcnow(), "event": kind, "data": data or {}}
        if os.environ.get("LOOPENG_PRESENTATION") == "1":
            from loopeng.presentation import format_event
            line = format_event(kind, data)
            if line is not None:
                print("[LOOP] " + line, flush=True)
        elif os.environ.get("LOOPENG_LIVE") == "1":
            visible = {
                "RUN_CREATED", "BASELINE_STAGED", "CANDIDATE_STAGED",
                "VERIFIER_RESULT", "PROPOSAL_REJECTED", "POLICY_DENIED",
                "EXPERIMENT_EVALUATED", "HYPOTHESIS_STAGED", "HELDOUT_EVALUATED_ONCE",
                "RUN_TERMINAL", "RUN_RESUMED", "STOP", "BASELINE_VALIDATED",
                "MODEL_REQUEST_STARTED", "MODEL_REQUEST_COMPLETED",
            }
            safe_fields = {
                "attempt", "public_passed", "protected_passed", "status", "reason",
                "validation_f1", "kept", "best_so_far_f1", "configuration", "proposer",
                "model", "input_tokens", "output_tokens", "cost_usd_reported",
            }
            if kind in visible:
                preview = {k: v for k, v in (data or {}).items() if k in safe_fields}
                print("[LOOP] " + kind + " " + json.dumps(preview, ensure_ascii=False), flush=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def export_summary(self, state: dict) -> None:
        write_json_atomic(self.directory / "summary.json", {
            "run_id": state["run_id"],
            "demo": state["demo"],
            "mode": state["mode"],
            "status": state["status"],
            "attempts_used": state["attempts_used"],
            "api_calls": state["api_calls"],
            "tokens_used": state["tokens_used"],
            "elapsed_seconds": round(state["elapsed_seconds"], 4),
            "budget": state["budget"],
            "history": state["attempt_history"],
            "details": state["details"],
        })


def add_elapsed(state: dict, start: float) -> None:
    state["elapsed_seconds"] += time.monotonic() - start


class InjectedInterruption(Exception):
    """Test-only crash injection after candidate staging."""
