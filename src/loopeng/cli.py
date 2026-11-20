"""Stable public CLI for the two Loop Engineering reference demonstrations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from loopeng.core import InjectedInterruption
from loopeng.demo_rd.pipeline import run as run_research
from loopeng.demo_se.pipeline import run as run_software


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopeng",
        description="Reproducible Loop Engineering demos (offline by default).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    software = commands.add_parser("se", help="Software Engineering verification loop")
    software.add_argument("--backend", choices=["offline", "openrouter"], default="offline")
    software.add_argument("--mode", choices=["single_pass", "feedback_only", "governed"], default="governed")
    software.add_argument(
        "--sandbox", choices=["auto", "trusted_local", "docker"], default="auto",
        help="auto = trusted_local for offline fixtures, Docker for OpenRouter code",
    )
    software.add_argument("--max-attempts", type=int, default=4)
    software.add_argument("--max-elapsed", type=float, default=120.0)
    software.add_argument("--resume", metavar="RUN_ID")
    software.add_argument("--out", type=Path, default=Path("runs"))
    software.add_argument("--live", action="store_true", help="Show event stream during execution")

    research = commands.add_parser("rd", help="Bounded ML experimentation loop")
    research.add_argument("--backend", choices=["offline", "openrouter"], default="offline")
    research.add_argument("--mode", choices=["single_pass", "governed"], default="governed")
    research.add_argument("--seed", type=int, default=2026)
    research.add_argument("--max-attempts", type=int, default=5)
    research.add_argument("--max-elapsed", type=float, default=120.0)
    research.add_argument("--resume", metavar="RUN_ID")
    research.add_argument("--out", type=Path, default=Path("runs"))
    research.add_argument("--live", action="store_true", help="Show event stream during execution")

    preflight = commands.add_parser("preflight", help="Check OpenRouter key and model")
    preflight.add_argument(
        "--probe", action="store_true", help="Make one billable structured-output inference request"
    )
    report = commands.add_parser("report", help="Display a saved run summary")
    report.add_argument("run_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            from loopeng.backends import OpenRouterChat

            client = OpenRouterChat()
            metadata = client.preflight()
            print(json.dumps(metadata, indent=2))
            if not metadata["advertises_structured_outputs"]:
                raise RuntimeError("Model does not advertise structured output support")
            if args.probe:
                schema = {
                    "type": "object",
                    "properties": {"ready": {"type": "boolean"}},
                    "required": ["ready"],
                    "additionalProperties": False,
                }
                answer, usage = client.ask_json(
                    "Return a single JSON object with ready=true.",
                    "This is a billable connectivity probe. Reply with ready=true.",
                    schema,
                )
                if answer.get("ready") is not True:
                    raise RuntimeError("Probe returned an unexpected payload")
                print("BILLABLE PROBE:", json.dumps({"result": answer, "usage": usage}, indent=2))
            return 0

        if args.command == "report":
            summary = args.run_dir / "summary.json"
            if not summary.is_file():
                raise FileNotFoundError(f"Summary not found: {summary}")
            print(summary.read_text(encoding="utf-8"))
            return 0

        if args.live:
            os.environ["LOOPENG_LIVE"] = "1"
        if args.command == "se":
            sandbox = (
                "docker" if args.backend == "openrouter" else "trusted_local"
            ) if args.sandbox == "auto" else args.sandbox
            store, state = run_software(
                root=args.out,
                backend=args.backend,
                mode=args.mode,
                sandbox=sandbox,
                max_attempts=args.max_attempts,
                resume_id=args.resume,
                max_elapsed_seconds=args.max_elapsed,
            )
            print(f"\nDEMO 1 — SOFTWARE ENGINEERING | {state['details']['demo_kind']}")
            print(f"run_id={state['run_id']} status={state['status']}")
            print("attempt | public | acceptance | candidate SHA256")
            for row in state["attempt_history"]:
                public = "PASS" if row["public_passed"] else "FAIL"
                acceptance = (
                    "SKIP" if row["protected_passed"] is None
                    else "PASS" if row["protected_passed"] else "FAIL"
                )
                print(f"{row['attempt']:7d} | {public:6} | {acceptance:10} | {row['candidate_sha256'][:12]}")
        else:
            store, state = run_research(
                root=args.out,
                backend=args.backend,
                mode=args.mode,
                seed=args.seed,
                max_attempts=args.max_attempts,
                max_elapsed_seconds=args.max_elapsed,
                resume_id=args.resume,
            )
            print(f"\nDEMO 2 — ML RESEARCH | {state['details']['demo_kind']}")
            print(f"run_id={state['run_id']} status={state['status']}")
            print(f"baseline validation F1={state['details']['baseline_validation']['f1']:.4f}")
            print("attempt | feature map | validation F1 | decision | best-so-far F1")
            for row in state["attempt_history"]:
                config = row["config"]
                decision = "KEEP" if row["kept"] else "REJECT"
                print(
                    f"{row['attempt']:7d} | {config['feature_map']:11} | "
                    f"{row['validation']['f1']:13.4f} | {decision:8} | {row['best_so_far_f1']:.4f}"
                )
            if state["details"].get("heldout_report"):
                holdout = state["details"]["heldout_report"]
                print(
                    "held-out F1 (assessed after selection): "
                    f"baseline={holdout['baseline']['f1']:.4f}, "
                    f"selected={holdout['selected']['f1']:.4f}"
                )
        print(f"Artifacts: {store.directory}")
        return 0 if state["status"] in ("ACCEPTED", "SEARCH_COMPLETE", "SINGLE_PASS_COMPLETE") else 4
    except InjectedInterruption as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        # Never print provider error bodies or secret-bearing HTTP headers.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; check the run directory before deciding whether to resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
