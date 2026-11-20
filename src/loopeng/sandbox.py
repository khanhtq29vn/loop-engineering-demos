"""Evaluate candidate outputs while keeping expected answers on the host.

The public repository contains the acceptance checks for reproducibility. They
are withheld from the proposer prompt and candidate sandbox, not secret from
readers of the repository. Docker is defense-in-depth, not a perfect sandbox.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from loopeng.demo_se.test_vectors import public_cases, protected_cases


class ExecutionError(RuntimeError):
    """Could not launch the candidate isolation boundary."""


def verify(candidate: Path, suite: str, mode: str, timeout: int = 12) -> dict:
    if suite == "public":
        cases = public_cases()
    elif suite == "acceptance":
        cases = protected_cases()
    else:
        raise ValueError("Unknown verification suite")

    candidate = Path(candidate).resolve(strict=True)
    runner = Path(__file__).parent / "demo_se" / "candidate_proxy.py"
    inputs = {"cases": [{"name": c["name"], "entries": c["entries"]} for c in cases]}
    container_name = None

    if mode == "trusted_local":
        # Defense in depth: reject any source not exactly one of the known fixtures.
        # This guard protects direct library calls as well as the CLI pipeline.
        from loopeng.demo_se.fixtures import CANDIDATES

        if candidate.read_text(encoding="utf-8") not in CANDIDATES:
            raise ExecutionError("trusted_local is restricted to bundled reference fixtures")
        command = [sys.executable, "-B", str(runner), str(candidate)]
    elif mode == "docker":
        if not shutil.which("docker"):
            raise ExecutionError("Docker CLI not installed; required for model-generated source")
        container_name = "loopeng-" + uuid.uuid4().hex[:12]
        command = [
            "docker", "run", "--name", container_name, "--rm", "--pull=never",
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=48", "--memory=256m",
            "--memory-swap=256m", "--cpus=1", "--user=65534:65534",
            "--tmpfs", "/tmp:rw,nosuid,noexec,size=16m",
            "--mount", f"type=bind,src={candidate},dst=/opt/work/ledger.py,readonly",
            "--mount", f"type=bind,src={runner.resolve()},dst=/opt/run/candidate_proxy.py,readonly",
            "--workdir", "/opt/work", "python:3.12-slim", "python", "-B",
            "/opt/run/candidate_proxy.py", "/opt/work/ledger.py",
        ]
    else:
        raise ValueError("Unknown sandbox mode")

    try:
        result = subprocess.run(
            command,
            input=json.dumps(inputs),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        if container_name:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
        return {
            "passed": False, "tests": len(cases), "failures": 0, "errors": 1,
            "details": ["TIMEOUT"], "runtime": mode,
        }
    except OSError as exc:
        raise ExecutionError(f"Cannot launch candidate runner ({type(exc).__name__})") from None

    if result.returncode != 0:
        return {
            "passed": False, "tests": len(cases), "failures": 0, "errors": 1,
            "details": [f"Runner exited with code {result.returncode}"], "runtime": mode,
        }
    try:
        payload = json.loads(result.stdout.strip())
        outcomes = payload["outcomes"]
        if not isinstance(outcomes, list) or len(outcomes) != len(cases):
            raise ValueError("Incomplete results")
    except (ValueError, TypeError, KeyError):
        return {
            "passed": False, "tests": len(cases), "failures": 0, "errors": 1,
            "details": ["Invalid candidate response"], "runtime": mode,
        }

    failures = []
    for expected, actual in zip(cases, outcomes):
        if not isinstance(actual, dict):
            failures.append(expected["name"])
            continue
        same = actual.get("name") == expected["name"]
        if "expected_exception" in expected:
            passed = same and actual.get("exception") == expected["expected_exception"]
        else:
            passed = (
                same and actual.get("exception") is None
                and actual.get("value") == expected["expected"]
            )
        if not passed:
            failures.append(expected["name"])
    return {
        "passed": not failures, "tests": len(cases), "failures": len(failures),
        "errors": 0, "details": failures[:6], "runtime": mode,
        "evaluation_boundary": "expected_answers_compared_on_host",
    }
