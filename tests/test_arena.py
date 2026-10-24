"""Game and API-boundary checks; no credentials or network required."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import arena_engine as arena


def game(**kwargs):
    return arena.Arena({
        "buyer_a": arena.Player("model-a", 100, 150, 0),
        "buyer_b": arena.Player("model-b", 80, 150, 0),
        "seller": arena.Player("model-s", 40, 0, 1),
    }, **kwargs)


def action(kind, price=None, buyer=None, message=""):
    return {"action": kind, "price": price, "buyer_id": buyer, "message": message}


class GameTests(unittest.TestCase):
    def test_private_observations_and_snapshot_independence(self):
        g = game()
        a = g.observe("buyer_a")
        b = g.observe("buyer_b")
        self.assertEqual(a["private_value"], 100)
        self.assertEqual(b["private_value"], 80)
        self.assertNotIn("value", a["public_balances"]["buyer_b"])
        g.bids["buyer_a"] = 55
        self.assertEqual(a["current_bids"], {})
        self.assertEqual(g.observe("buyer_b")["current_bids"], {})
        self.assertEqual(g.observe("seller")["current_bids"], {"buyer_a": 55})
        a["previous_rounds"].append("tamper")
        self.assertEqual(g.history, [])

    def test_trade_conservation_and_payoffs(self):
        g = game()
        g.bids = {"buyer_a": 70, "buyer_b": 75}
        g.settle("buyer_b")
        s = g.summary()
        self.assertEqual(s["payoffs"], {"buyer_a": 0, "buyer_b": 5, "seller": 35})
        self.assertAlmostEqual(s["allocation_efficiency"], 2 / 3)
        self.assertEqual(sum(p.cash for p in g.players.values()), 300)
        self.assertEqual(sum(p.inventory for p in g.players.values()), 1)
        with self.assertRaises(ValueError):
            g.settle("buyer_a")

    def test_no_trade_and_zero_optimum(self):
        g = game()
        self.assertEqual(g.summary()["allocation_efficiency"], 0)
        g.players["seller"].value = 150
        self.assertIsNone(g.summary()["allocation_efficiency"])

    def test_negative_payoffs_are_observable(self):
        g = game()
        g.players["buyer_b"].value = 20
        g.bids = {"buyer_b": 30}
        self.assertIsNone(g.validate("seller", action("accept", buyer="buyer_b")))
        g.settle("buyer_b")
        self.assertEqual(g.summary()["realized_surplus"], -20)
        self.assertLess(g.summary()["allocation_efficiency"], 0)

    def test_illegal_and_malformed_actions(self):
        g = game()
        for a in (action("bid", -1), action("bid", 151), action("bid", True),
                  action("bid", 50.5), action("accept", buyer="buyer_a"),
                  action("pass", 5), action("bid", 50, buyer="buyer_b"),
                  {}, [], action("bid", 50, message="x" * 401)):
            self.assertIsNotNone(g.validate("buyer_a", a), a)
        self.assertIsNotNone(g.validate("seller", action("accept", buyer="buyer_b")))
        self.assertIsNotNone(g.validate("seller", action("accept", buyer=[])))
        self.assertIsNone(g.validate("buyer_a", action("bid", 0)))

    def test_chat_disabled(self):
        g = game(chat=False)
        self.assertIsNotNone(g.validate("buyer_a", action("bid", 50, message="hello")))
        self.assertIsNone(g.validate("buyer_a", action("bid", 50)))

    def run_policy(self, g, policy):
        with tempfile.TemporaryDirectory() as tmp:
            journal = arena.Journal(Path(tmp) / "episode")
            with contextlib.redirect_stdout(io.StringIO()):
                result = arena.play(g, policy, journal)
            events = [json.loads(line) for line in (journal.directory / "events.jsonl").read_text().splitlines()]
            return result, events

    def test_scripted_multiround_and_expiry(self):
        g = game()
        result, events = self.run_policy(g, arena.ScriptedPolicy())
        self.assertTrue(result["agreement"])
        self.assertEqual(result["trade"]["round"], 2)
        self.assertEqual(g.bids, {})
        self.assertEqual(len([e for e in events if e["kind"] == "trade"]), 1)

    def test_no_sale_stops_at_budget(self):
        class RejectPolicy:
            def choose(self, model, observation):
                return action("pass" if observation["you"] in arena.BUYERS else "reject")
        g = game(max_rounds=2)
        result, events = self.run_policy(g, RejectPolicy())
        self.assertFalse(result["agreement"])
        self.assertEqual(len(g.history), 2)
        self.assertEqual(len(events), 6)

    def test_frozen_buyer_observations_and_current_seller_messages(self):
        observations = []
        class RecordingPolicy(arena.ScriptedPolicy):
            def choose(self, model, observation):
                observations.append(observation)
                return super().choose(model, observation)
        self.run_policy(game(max_rounds=1), RecordingPolicy())
        self.assertEqual(observations[1]["current_bids"], {})
        self.assertEqual(observations[1]["previous_rounds"], [])
        self.assertEqual(len(observations[2]["current_bids"]), 2)
        self.assertEqual(len(observations[2]["current_buyer_messages"]), 2)

    def test_invalid_actions_count_without_execution(self):
        class InvalidPolicy:
            def choose(self, model, observation):
                return action("bid", -1)
        g = game(max_rounds=1)
        result, _ = self.run_policy(g, InvalidPolicy())
        self.assertFalse(result["agreement"])
        self.assertEqual(result["invalid_actions"], 3)
        self.assertEqual(sum(p.cash for p in g.players.values()), 300)


class CodexBoundaryTests(unittest.TestCase):
    def test_codex_action_schema_login_and_information_boundaries(self):
        requests = []
        def run(command, **kwargs):
            if command[1:3] == ["login", "status"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="Logged in using ChatGPT")
            requests.append((command, kwargs))
            output = Path(command[command.index("--output-last-message") + 1])
            self.assertNotEqual(output.parent, Path.cwd())
            output.write_text(json.dumps(action("bid", 55)))
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
                "type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 20}}))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(arena.shutil, "which", return_value="/mock/codex"), \
                patch.object(arena.subprocess, "run", side_effect=run), \
                patch.dict(arena.os.environ, {"OPENAI_API_KEY": "placeholder-test-only"}):
            policy = arena.CodexPolicy(arena.Journal(Path(tmp) / "run"))
            with contextlib.redirect_stdout(io.StringIO()):
                result = policy.choose("test-model", game().observe("buyer_a"))
            self.assertEqual(result["price"], 55)
            self.assertEqual(policy.input_tokens, 50)
        command, kwargs = requests[0]
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn('forced_login_method="chatgpt"', command)
        self.assertIn("features.shell_tool=false", command)
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertEqual(command[-1], "-")
        self.assertIn('"private_value": 100', kwargs["input"])
        self.assertNotIn('"private_value": 80', kwargs["input"])

    def test_missing_cli_gives_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(arena.shutil, "which", return_value=None), \
                patch.object(arena.Path, "home", return_value=Path(tmp)):
            with self.assertRaisesRegex(RuntimeError, "Codex CLI not found"):
                arena.CodexPolicy(None)

    def test_extension_binary_found_when_terminal_path_lacks_codex(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(arena.shutil, "which", return_value=None), \
                patch.object(arena.Path, "home", return_value=Path(tmp)), \
                patch.object(arena.platform, "system", return_value="Darwin"), \
                patch.object(arena.platform, "machine", return_value="arm64"):
            binary = Path(tmp) / ".vscode/extensions/openai.chatgpt-1.0/bin/macos-aarch64/codex"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            self.assertEqual(arena.find_codex(), str(binary.resolve()))

    def test_explicit_invalid_binary_is_not_silently_ignored(self):
        with patch.dict(arena.os.environ, {"CODEX_BINARY": "/missing-codex-binary"}):
            with self.assertRaisesRegex(RuntimeError, "CODEX_BINARY"):
                arena.find_codex()

    def test_api_login_is_not_used_as_subscription_login(self):
        with patch.object(arena.shutil, "which", return_value="/mock/codex"), \
                patch.object(arena.subprocess, "run", return_value=SimpleNamespace(
                    returncode=0, stdout="", stderr="Logged in using API key")):
            with self.assertRaisesRegex(RuntimeError, "ChatGPT sign-in"):
                arena.CodexPolicy(None)

    def test_tool_event_excludes_episode(self):
        def run(command, **kwargs):
            if command[1:3] == ["login", "status"]:
                return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
                "type": "item.completed", "item": {"type": "command_execution"}}))
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(arena.shutil, "which", return_value="/mock/codex"), \
                patch.object(arena.subprocess, "run", side_effect=run):
            policy = arena.CodexPolicy(arena.Journal(Path(tmp) / "run"))
            with contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaisesRegex(RuntimeError, "tool action"):
                policy.choose("test-model", game().observe("buyer_a"))


class APIBoundaryTests(unittest.TestCase):
    def call(self, text, status="completed"):
        captured = {}
        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id="response-test", model="returned-model", status=status,
                                   output_text=text, usage=None)
        with tempfile.TemporaryDirectory() as tmp:
            policy = arena.LivePolicy.__new__(arena.LivePolicy)
            policy.client = SimpleNamespace(responses=SimpleNamespace(create=create))
            policy.journal = arena.Journal(Path(tmp) / "episode")
            policy.calls = policy.input_tokens = policy.output_tokens = 0
            policy.max_output_tokens = 512
            result = policy.choose("test-model", game().observe("buyer_a"))
            return result, captured

    def test_real_adapter_builds_structured_private_request(self):
        result, request = self.call(json.dumps(action("bid", 55)))
        self.assertEqual(result["price"], 55)
        self.assertEqual(request["model"], "test-model")
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertFalse(request["store"])
        observation = json.loads(request["input"])
        self.assertEqual(observation["private_value"], 100)
        self.assertNotIn("private_value", observation["public_balances"]["buyer_b"])

    def test_refusal_truncation_and_bad_json_abort(self):
        for text, status in (("", "completed"), ("{}", "incomplete"), ("not json", "completed")):
            with self.subTest(text=text, status=status):
                with self.assertRaises(RuntimeError):
                    self.call(text, status)


if __name__ == "__main__":
    unittest.main()
