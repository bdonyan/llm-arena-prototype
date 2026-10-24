"""Experiment design, isolation, resumption, and report denominator checks."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import arena_engine as engine
from experiment_config import ROLES, expand_cases, load_config
from experiment_report import generate_report, latest_results
from run_experiments import RoutedPolicy, execute_episode, prepare_suite, run_suite

ROOT = Path(__file__).resolve().parents[1]


class ExperimentTests(unittest.TestCase):
    def config(self):
        config = load_config(ROOT / "experiments/pilot.json")
        config["scenarios"] = config["scenarios"][:1]
        return config

    def test_full_factorial_coverage_and_stable_ids(self):
        config = load_config(ROOT / "experiments/full.json")
        cases = expand_cases(config)
        self.assertEqual(len(cases), 72)
        self.assertEqual(len({c["id"] for c in cases}), 72)
        self.assertEqual([c["id"] for c in cases], [c["id"] for c in expand_cases(config)])
        assignments = {tuple(c["roles"][role] for role in ROLES) for c in cases}
        self.assertEqual(len(assignments), 6)
        for role in ROLES:
            for alias in config["agents"]:
                self.assertEqual(sum(c["roles"][role] == alias for c in cases), 24)

    def test_invalid_config_rejected_before_running(self):
        for change in ({"rounds": True}, {"chat_modes": ["false"]}, {"games": ["unknown"]},
                       {"repetitions": 0}, {"api_key": "should-not-be-in-config"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                config = self.config()
                config.update(change)
                path = Path(tmp) / "config.json"
                path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    load_config(path)

    def test_open_bids_reveal_only_prior_current_actions_and_support_reversal(self):
        observations = []
        class Recording(engine.ScriptedPolicy):
            def choose(self, model, observation):
                observations.append(observation)
                return super().choose(model, observation)
        with tempfile.TemporaryDirectory() as tmp:
            arena = engine.create_arena(dict(zip(ROLES, ["a", "b", "s"])),
                                        dict(zip(ROLES, [100, 80, 40])), game="open_bids",
                                        rounds=1, buyer_order=engine.BUYERS[::-1])
            with contextlib.redirect_stdout(io.StringIO()):
                engine.play(arena, Recording(), engine.Journal(Path(tmp) / "episode"))
        self.assertEqual(observations[0]["you"], "buyer_b")
        self.assertEqual(observations[0]["current_bids"], {})
        self.assertEqual(observations[1]["current_bids"], {"buyer_b": 35})
        self.assertEqual(observations[1]["current_buyer_messages"][0]["actor"], "buyer_b")
        self.assertNotIn("value", observations[1]["public_balances"]["buyer_b"])

    def test_matched_reports_and_resuming_do_not_duplicate(self):
        config = self.config()
        cases = expand_cases(config)[:2]
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            directory = Path(tmp) / "suite"
            manifest = prepare_suite(directory, config, cases, True)
            self.assertEqual(run_suite(directory, manifest), 0)
            self.assertEqual(run_suite(directory, manifest), 0)
            metrics = generate_report(directory)
            self.assertEqual(metrics["completed"], 2)
            self.assertEqual(metrics["saved_attempts"], 2)
            self.assertEqual(len(metrics["matched_chat_pairs"]), 1)
            self.assertEqual(metrics["matched_chat_pairs"][0]["efficiency_delta"], 0)
            self.assertEqual(metrics["usage_all_saved_attempts"]["attempted_requests"], 0)
            self.assertIn("NOT LLM RESULTS", (directory / "report.html").read_text())
            for artifact in ("episodes.csv", "players.csv", "report.md", "metrics.json"):
                self.assertTrue((directory / artifact).exists())

    def test_failures_excluded_from_outcomes_but_retry_usage_retained(self):
        config = self.config()
        cases = expand_cases(config)[:2]
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            directory = Path(tmp) / "suite"
            prepare_suite(directory, config, cases, True)
            execute_episode(cases[0], directory / "episodes" / cases[0]["id"] / "attempt-001", True)
            journal = engine.Journal(directory / "episodes" / cases[1]["id"] / "attempt-001")
            journal.finish({"case": cases[1], "dry_run": True, "status": "aborted",
                            "error": "<script>unsafe</script>", "usage": {"attempted_requests": 2}})
            metrics = generate_report(directory)
            self.assertEqual(metrics["completed"], 1)
            self.assertEqual(metrics["failed_or_incomplete"], 1)
            self.assertEqual(metrics["matched_chat_pairs"], [])
            self.assertIsNone(next(r for r in metrics["conditions"] if not r["chat"])["agreement_rate"])
            self.assertNotIn("<script>unsafe</script>", (directory / "report.html").read_text())
            execute_episode(cases[1], directory / "episodes" / cases[1]["id"] / "attempt-002", True)
            metrics = generate_report(directory)
            self.assertEqual(metrics["completed"], 2)
            self.assertEqual(metrics["saved_attempts"], 3)
            self.assertEqual(metrics["usage_all_saved_attempts"]["attempted_requests"], 2)

    def test_game_comparisons_match_budgets_assignments_and_chat(self):
        config = load_config(ROOT / "experiments/full.json")
        all_cases = expand_cases(config)
        cases = [all_cases[i] for i in (0, 1, 36, 37)]
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            directory = Path(tmp) / "suite"
            manifest = prepare_suite(directory, config, cases, True)
            run_suite(directory, manifest)
            metrics = generate_report(directory)
            self.assertEqual(len(metrics["matched_game_pairs"]), 2)
            self.assertEqual(len(metrics["matched_chat_pairs"]), 2)
            self.assertEqual({p["chat"] for p in metrics["matched_game_pairs"]}, {True, False})

    def test_undefined_efficiency_is_not_reported_as_zero(self):
        config = self.config()
        config["scenarios"][0]["values"] = {"buyer_a": 20, "buyer_b": 30, "seller": 150}
        cases = expand_cases(config)[:2]
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            directory = Path(tmp) / "suite"
            manifest = prepare_suite(directory, config, cases, True)
            run_suite(directory, manifest)
            metrics = generate_report(directory)
            self.assertTrue(all(c["mean_efficiency"] is None and c["efficiency_n"] == 0
                                for c in metrics["conditions"]))
            self.assertIsNone(metrics["matched_chat_pairs"][0]["efficiency_delta"])

    def test_request_cap_stops_before_launching_an_episode(self):
        config = self.config()
        cases = expand_cases(config)[:1]
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            directory = Path(tmp) / "suite"
            manifest = prepare_suite(directory, config, cases, False)
            with patch("run_experiments.execute_episode") as execute:
                self.assertEqual(run_suite(directory, manifest, max_requests=17), 0)
                execute.assert_not_called()
            self.assertEqual(generate_report(directory)["pending"], 1)

    def test_different_config_cannot_contaminate_resume(self):
        config = self.config()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "suite"
            prepare_suite(directory, config, expand_cases(config), True)
            changed = {**config, "rounds": 2}
            with self.assertRaisesRegex(ValueError, "different config_hash"):
                prepare_suite(directory, changed, expand_cases(changed), True)
            with self.assertRaisesRegex(ValueError, "different dry_run"):
                prepare_suite(directory, config, expand_cases(config), False)

    def test_interrupted_episode_is_visible_not_silently_skipped(self):
        config = self.config()
        cases = expand_cases(config)[:1]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "suite"
            prepare_suite(directory, config, cases, True)
            (directory / "episodes" / cases[0]["id"] / "attempt-001").mkdir(parents=True)
            self.assertEqual(latest_results(directory)[0]["status"], "incomplete")
            self.assertEqual(generate_report(directory)["failed_or_incomplete"], 1)

    def test_routing_uses_roles_and_accounts_usage_on_errors(self):
        case = expand_cases(self.config())[0]
        instances = []
        class FakeProvider:
            def __init__(self, *args):
                self.calls = self.input_tokens = self.output_tokens = 0
                instances.append(self)
            def choose(self, model, observation):
                self.calls += 1
                self.input_tokens += 123
                raise RuntimeError("transport failed")
        with tempfile.TemporaryDirectory() as tmp, patch.object(engine, "CodexPolicy", FakeProvider):
            policy = RoutedPolicy(case, engine.Journal(Path(tmp) / "episode"), False)
            with self.assertRaises(RuntimeError):
                policy.choose("arbitrary-model", {"you": "buyer_b"})
            self.assertEqual(policy.by_role["buyer_b"]["attempted_requests"], 1)
            self.assertEqual(policy.by_role["buyer_b"]["input_tokens"], 123)
            self.assertEqual(policy.by_role["buyer_a"]["input_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
