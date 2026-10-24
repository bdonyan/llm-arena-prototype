"""Validate a declarative experiment and expand it to immutable episode cases."""
from __future__ import annotations

import hashlib
import itertools
import json
import re
from pathlib import Path

from arena_engine import BUYERS, GAME_RULES, create_arena

ROLES = (*BUYERS, "seller")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Experiment configuration must be an object")
    allowed = {"name", "agents", "assignments", "scenarios", "games", "chat_modes",
               "repetitions", "rounds", "buyer_orders", "codex_timeout", "max_output_tokens"}
    if set(config) - allowed:
        raise ValueError(f"Unknown configuration fields: {set(config) - allowed}")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", config.get("name", "")):
        raise ValueError("name must contain only letters, digits, underscores, and hyphens")
    agents = config.get("agents")
    if not isinstance(agents, dict) or len(agents) != 3:
        raise ValueError("Define exactly three named agents")
    for name, agent in agents.items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or not isinstance(agent, dict):
            raise ValueError("Agent names must be simple identifiers and settings must be objects")
        if set(agent) != {"backend", "model"}:
            raise ValueError(f"Agent {name}: expected only backend and model")
        if agent["backend"] not in ("codex", "openai") or not isinstance(agent["model"], str) or not agent["model"].strip():
            raise ValueError(f"Agent {name}: use backend codex/openai and a nonempty model ID")
    defaults = {"assignments": "cyclic", "games": ["sealed_bids"], "chat_modes": [True, False],
                "repetitions": 1, "rounds": 6, "buyer_orders": [list(BUYERS)],
                "codex_timeout": 180, "max_output_tokens": 512}
    config = {**defaults, **config}
    for name, low, high in (("repetitions", 1, 1000), ("rounds", 1, 20),
                            ("codex_timeout", 1, 3600), ("max_output_tokens", 128, 4096)):
        if type(config[name]) is not int or not low <= config[name] <= high:
            raise ValueError(f"{name} must be an integer in [{low},{high}]")
    if config["assignments"] not in ("cyclic", "all_permutations"):
        raise ValueError("assignments must be cyclic or all_permutations")
    for key in ("games", "chat_modes", "buyer_orders", "scenarios"):
        if not isinstance(config.get(key), list) or not config[key]:
            raise ValueError(f"{key} must be a nonempty list")
        if len({json.dumps(v, sort_keys=True) for v in config[key]}) != len(config[key]):
            raise ValueError(f"{key} contains duplicate entries")
    if any(g not in GAME_RULES for g in config["games"]):
        raise ValueError(f"games must be selected from {list(GAME_RULES)}")
    if any(type(mode) is not bool for mode in config["chat_modes"]):
        raise ValueError("chat_modes must contain booleans")
    scenario_names = set()
    for scenario in config["scenarios"]:
        if not isinstance(scenario, dict) or set(scenario) != {"name", "values"}:
            raise ValueError("Each scenario needs exactly name and values")
        name = scenario["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name in scenario_names:
            raise ValueError("Scenario names must be distinct simple identifiers")
        scenario_names.add(name)
        for game, order in itertools.product(config["games"], config["buyer_orders"]):
            create_arena(dict(zip(ROLES, agents)), scenario["values"], game=game,
                         rounds=config["rounds"], buyer_order=order)
    return config


def expand_cases(config: dict) -> list[dict]:
    names = list(config["agents"])
    assignments = (list(itertools.permutations(names)) if config["assignments"] == "all_permutations"
                   else [tuple(names[n:] + names[:n]) for n in range(3)])
    cases = []
    for game, scenario, assignment, order, repetition, chat in itertools.product(
        config["games"], config["scenarios"], assignments, config["buyer_orders"],
        range(1, config["repetitions"] + 1), config["chat_modes"]
    ):
        case = {"game": game, "scenario": scenario["name"], "values": scenario["values"],
                "roles": dict(zip(ROLES, assignment)), "agents": config["agents"],
                "buyer_order": order, "repetition": repetition, "chat": chat,
                "rounds": config["rounds"], "codex_timeout": config["codex_timeout"],
                "max_output_tokens": config["max_output_tokens"]}
        case["id"] = digest(case)[:16]
        cases.append(case)
    return cases
