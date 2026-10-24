#!/usr/bin/env python3
"""Preview, execute, resume, and report a configurable arena experiment."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import arena_engine as engine
from experiment_config import ROLES, digest, expand_cases, load_config
from experiment_report import generate_report, latest_results


class RoutedPolicy:
    """Select a model/backend per role without coupling providers to game rules."""
    def __init__(self, case: dict, journal: engine.Journal, dry_run: bool):
        self.case, self.journal, self.dry_run = case, journal, dry_run
        self.providers = {}
        self.by_role = {role: {"input_tokens": 0, "output_tokens": 0, "attempted_requests": 0}
                        for role in ROLES}

    def choose(self, model, observation):
        role = observation["you"]
        agent = self.case["agents"][self.case["roles"][role]]
        backend = "scripted" if self.dry_run else agent["backend"]
        if backend not in self.providers:
            if backend == "scripted":
                self.providers[backend] = engine.ScriptedPolicy()
            elif backend == "codex":
                self.providers[backend] = engine.CodexPolicy(self.journal, self.case["codex_timeout"])
            else:
                key = os.environ.get("OPENAI_API_KEY", "").strip()
                if not key:
                    raise RuntimeError("Set OPENAI_API_KEY to run an OpenAI API agent in a batch")
                self.providers[backend] = engine.LivePolicy(key, self.journal, self.case["max_output_tokens"])
        provider = self.providers[backend]
        before = (provider.calls, provider.input_tokens, provider.output_tokens)
        try:
            return provider.choose(model, observation)
        finally:
            usage = self.by_role[role]
            usage["attempted_requests"] += provider.calls - before[0]
            usage["input_tokens"] += provider.input_tokens - before[1]
            usage["output_tokens"] += provider.output_tokens - before[2]

    def close(self):
        for provider in self.providers.values():
            if isinstance(provider, engine.LivePolicy):
                provider.client.close()


def execute_episode(case: dict, directory: Path, dry_run: bool) -> dict:
    journal = engine.Journal(directory)
    models = {role: case["agents"][alias]["model"] for role, alias in case["roles"].items()}
    arena = engine.create_arena(models, case["values"], game=case["game"], rounds=case["rounds"],
                                chat=case["chat"], buyer_order=case["buyer_order"])
    policy = RoutedPolicy(case, journal, dry_run)
    journal.write("configuration", case=case, dry_run=dry_run, rules=engine.RULES,
                  protocol_rules=arena.protocol_rules(), action_schema=engine.ACTION_SCHEMA)
    start = time.monotonic()
    interrupted = False
    with (directory / "console.txt").open("w", encoding="utf-8") as console, contextlib.redirect_stdout(console):
        try:
            result = engine.play(arena, policy, journal)
            result["status"] = "completed"
        except (Exception, KeyboardInterrupt) as exc:
            interrupted = isinstance(exc, KeyboardInterrupt)
            result = {"status": "aborted", "error": "Interrupted by user" if interrupted else str(exc),
                      "completed_rounds": len(arena.history)}
            journal.write("aborted", error=result["error"])
        finally:
            policy.close()
    result.update({"case": case, "dry_run": dry_run,
                   "elapsed_seconds": time.monotonic() - start,
                   "finished_at": datetime.now(timezone.utc).isoformat(),
                   "usage_by_role": policy.by_role,
                   "usage": {key: sum(u[key] for u in policy.by_role.values())
                             for key in ("attempted_requests", "input_tokens", "output_tokens")},
                   "interrupted": interrupted})
    journal.finish(result)
    return result


def source_hash() -> str:
    return digest({name: Path(__file__).with_name(name).read_text(encoding="utf-8")
                   for name in ("arena_engine.py", "experiment_config.py", "run_experiments.py")})


def prepare_suite(directory: Path, config: dict, cases: list[dict], dry_run: bool) -> dict:
    manifest = {"config": config, "cases": cases, "dry_run": dry_run,
                "config_hash": digest(config), "source_hash": source_hash()}
    path = directory / "manifest.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        for key in ("config_hash", "source_hash", "dry_run"):
            if existing[key] != manifest[key]:
                raise ValueError(f"Existing suite has different {key}. Use a new --output-dir; results cannot be mixed.")
        return existing
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Output directory is nonempty and has no manifest; choose another directory")
    directory.mkdir(parents=True, exist_ok=True)
    manifest["created_at"] = datetime.now(timezone.utc).isoformat()
    manifest["python_version"] = sys.version
    source = directory / "source"
    source.mkdir()
    for name in ("arena_engine.py", "experiment_config.py", "experiment_report.py", "run_experiments.py"):
        (source / name).write_text(Path(__file__).with_name(name).read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def run_suite(directory: Path, manifest: dict, *, limit: int | None = None,
              max_requests: int | None = None, retry_failed=False) -> int:
    latest = {r["case"]["id"]: r for r in latest_results(directory)}
    started = spent = 0
    failed = False
    # Prevent two batch runners from duplicating the same cases. A hard crash may
    # leave this marker; the error explains how to recover without altering data.
    lock = directory / ".running"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise ValueError(f"Suite is already running, or a previous process crashed. "
                         f"After confirming no runner is active, remove only {lock} and resume.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        for index, case in enumerate(manifest["cases"], 1):
            old = latest.get(case["id"])
            if old and (old["status"] == "completed" or not retry_failed):
                continue
            if limit is not None and started >= limit:
                break
            worst_case = 0 if manifest["dry_run"] else 3 * case["rounds"]
            if max_requests is not None and spent + worst_case > max_requests:
                print("Stopped before next episode: its worst-case request count exceeds the remaining cap.")
                break
            parent = directory / "episodes" / case["id"]
            parent.mkdir(parents=True, exist_ok=True)
            attempt = max([int(p.name.split("-")[-1]) for p in parent.glob("attempt-*")], default=0) + 1
            destination = parent / f"attempt-{attempt:03d}"
            print(f"[{index}/{len(manifest['cases'])}] {case['game']} / {case['scenario']} / "
                  f"chat={case['chat']} / {case['roles']} / repeat={case['repetition']}", flush=True)
            result = execute_episode(case, destination, manifest["dry_run"])
            started += 1
            spent += result["usage"]["attempted_requests"]
            print(f"  {result['status']}; requests={result['usage']['attempted_requests']}; "
                  f"elapsed={result['elapsed_seconds']:.1f}s", flush=True)
            generate_report(directory)
            if result["status"] != "completed":
                failed = True
                print(f"  {result['error']}\nStopping batch; failure is saved. Use --retry-failed after resolving it.")
                break
    finally:
        lock.unlink(missing_ok=True)
        generate_report(directory)
    print(f"Report: {(directory / 'report.html').resolve()}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("experiments/pilot.json"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Preview only (the default)")
    mode.add_argument("--dry-run", action="store_true", help="Run scripted players, no model usage")
    mode.add_argument("--run", action="store_true", help="Run real players and consume model allowance")
    mode.add_argument("--report-only", action="store_true", help="Rebuild an existing suite report without model calls")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--limit", type=int, help="Maximum new episodes during this invocation")
    parser.add_argument("--max-requests", type=int, help="Cap player requests in this invocation; reserve worst case per episode")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if any(v is not None and v < 1 for v in (args.limit, args.max_requests)):
        parser.error("--limit and --max-requests must be positive")
    try:
        if args.report_only:
            if not args.output_dir:
                parser.error("--report-only requires --output-dir")
            generate_report(args.output_dir)
            print(f"Report: {(args.output_dir / 'report.html').resolve()}")
            return 0
        config = load_config(args.config)
        cases = expand_cases(config)
        print(f"{config['name']}: {len(cases)} episodes; at most {sum(3*c['rounds'] for c in cases)} player requests.")
        print(f"Games: {config['games']}; assignments: {config['assignments']}; "
              f"repetitions: {config['repetitions']}; chat modes: {config['chat_modes']}")
        print("Models:", json.dumps(config["agents"]))
        print("Model access is not verified by this preview. Codex retries and input overhead are not capped here.")
        if not args.run and not args.dry_run:
            print("Preview only. Add --dry-run for a scripted rehearsal or --run for real model calls.")
            return 0
        directory = args.output_dir or Path("runs/experiments") / (config["name"] + ("-scripted" if args.dry_run else "-live"))
        manifest = prepare_suite(directory, config, cases, args.dry_run)
        return run_suite(directory, manifest, limit=args.limit, max_requests=args.max_requests,
                         retry_failed=args.retry_failed)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Experiment error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
