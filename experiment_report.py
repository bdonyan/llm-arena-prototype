"""Offline reporting: outcomes, matched conditions, role metrics, and transcripts."""
from __future__ import annotations

from collections import defaultdict
import csv
import html
import json
from pathlib import Path
import statistics

from experiment_config import ROLES, digest


def latest_results(directory: Path) -> list[dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    results = []
    for case in manifest["cases"]:
        attempts = sorted((directory / "episodes" / case["id"]).glob("attempt-*"))
        if not attempts:
            continue
        path = attempts[-1] / "summary.json"
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
        else:
            result = {"case": case, "status": "incomplete", "dry_run": manifest["dry_run"],
                      "error": "No final summary: episode is still running or was interrupted."}
        results.append({**result, "_directory": str(attempts[-1].relative_to(directory)),
                        "_attempts": len(attempts)})
    return results


def mean(values):
    valid = [v for v in values if v is not None]
    return statistics.fmean(valid) if valid else None


def sd(values):
    valid = [v for v in values if v is not None]
    return statistics.stdev(valid) if len(valid) > 1 else None


def fmt(value):
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_report(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    results = latest_results(directory)
    completed = [r for r in results if r["status"] == "completed"]
    failed = [r for r in results if r["status"] != "completed"]
    # Include the costs of every attempt, even failed attempts later retried.
    all_attempts = [json.loads(p.read_text(encoding="utf-8"))
                    for p in (directory / "episodes").glob("*/attempt-*/summary.json")]
    usage = {key: sum(r.get("usage", {}).get(key, 0) for r in all_attempts)
             for key in ("attempted_requests", "input_tokens", "output_tokens")}
    rows, player_rows = [], []
    for r in results:
        case = r["case"]
        row = {"case_id": case["id"], "status": r["status"], "dry_run": r["dry_run"],
               "game": case["game"], "scenario": case["scenario"], "chat": case["chat"],
               "repetition": case["repetition"], "buyer_order": ",".join(case["buyer_order"]),
               "round_budget": case["rounds"], "attempts": r["_attempts"],
               "agreement": r.get("agreement"), "price": (r.get("trade") or {}).get("price"),
               "rounds_played": r.get("rounds_played"), "efficiency": r.get("allocation_efficiency"),
               "surplus": r.get("realized_surplus"), "invalid_actions": r.get("invalid_actions"),
               "elapsed_seconds": r.get("elapsed_seconds"), "error": r.get("error", ""),
               "path": r["_directory"]}
        for role in ROLES:
            alias = case["roles"][role]
            agent = case["agents"][alias]
            row[role] = alias
            player_rows.append({"case_id": case["id"], "status": r["status"], "game": case["game"],
                                "scenario": case["scenario"], "chat": case["chat"], "role": role,
                                "alias": alias, "backend": agent["backend"], "model": agent["model"],
                                "value": case["values"][role], "payoff": r.get("payoffs", {}).get(role),
                                "invalid_actions": r.get("invalid_actions_by_role", {}).get(role),
                                **r.get("usage_by_role", {}).get(role, {})})
        rows.append(row)
    episode_fields = ["case_id", "status", "dry_run", "game", "scenario", "chat", "repetition",
                      *ROLES, "buyer_order", "round_budget", "attempts", "agreement", "price",
                      "rounds_played", "efficiency", "surplus", "invalid_actions", "elapsed_seconds", "error", "path"]
    write_csv(directory / "episodes.csv", rows, episode_fields)
    write_csv(directory / "players.csv", player_rows,
              ["case_id", "status", "game", "scenario", "chat", "role", "alias", "backend", "model",
               "value", "payoff", "invalid_actions", "input_tokens", "output_tokens", "attempted_requests"])

    conditions = defaultdict(list)
    for row in rows:
        conditions[(row["game"], row["scenario"], row["chat"])].append(row)
    condition_metrics = []
    for (game, scenario, chat), group in sorted(conditions.items()):
        valid = [r for r in group if r["status"] == "completed"]
        condition_metrics.append({"game": game, "scenario": scenario, "chat": chat,
                                  "attempted_cases": len(group), "completed": len(valid),
                                  "agreement_rate": mean([int(r["agreement"]) for r in valid]),
                                  "mean_price_if_sold": mean([r["price"] for r in valid]),
                                  "mean_efficiency": mean([r["efficiency"] for r in valid]),
                                  "efficiency_n": sum(r["efficiency"] is not None for r in valid),
                                  "mean_rounds": mean([r["rounds_played"] for r in valid]),
                                  "invalid_actions": sum(r["invalid_actions"] for r in valid)})
    by_role = defaultdict(list)
    for row in player_rows:
        if row["status"] == "completed":
            by_role[(row["game"], row["chat"], row["role"], row["alias"], row["backend"], row["model"])].append(row)
    role_metrics = []
    for (game, chat, role, alias, backend, model), group in sorted(by_role.items()):
        role_metrics.append({"game": game, "chat": chat, "role": role, "alias": alias,
                             "backend": backend, "model": model, "n": len(group),
                             "mean_payoff": mean([r["payoff"] for r in group]),
                             "payoff_sample_sd": sd([r["payoff"] for r in group]),
                             "negative_payoffs": sum(r["payoff"] < 0 for r in group),
                             "invalid_actions": sum(r["invalid_actions"] for r in group)})
    pairs = defaultdict(dict)
    for r in completed:
        match = {k: v for k, v in r["case"].items() if k not in ("chat", "id")}
        pairs[digest(match)][r["case"]["chat"]] = r
    paired_rows = []
    for pair in pairs.values():
        if True not in pair or False not in pair:
            continue
        on, off = pair[True], pair[False]
        e_on, e_off = on["allocation_efficiency"], off["allocation_efficiency"]
        paired_rows.append({"game": on["case"]["game"], "scenario": on["case"]["scenario"],
                            "chat_case": on["case"]["id"], "no_chat_case": off["case"]["id"],
                            "agreement_delta": int(on["agreement"]) - int(off["agreement"]),
                            "efficiency_delta": e_on - e_off if e_on is not None and e_off is not None else None,
                            **{role + "_payoff_delta": on["payoffs"][role] - off["payoffs"][role] for role in ROLES}})
    game_pairs = defaultdict(dict)
    for r in completed:
        match = {k: v for k, v in r["case"].items() if k not in ("game", "id")}
        game_pairs[digest(match)][r["case"]["game"]] = r
    paired_games = []
    for pair in game_pairs.values():
        if "open_bids" not in pair or "sealed_bids" not in pair:
            continue
        opened, sealed = pair["open_bids"], pair["sealed_bids"]
        e_open, e_sealed = opened["allocation_efficiency"], sealed["allocation_efficiency"]
        paired_games.append({"scenario": opened["case"]["scenario"], "chat": opened["case"]["chat"],
                             "open_case": opened["case"]["id"], "sealed_case": sealed["case"]["id"],
                             "agreement_delta": int(opened["agreement"]) - int(sealed["agreement"]),
                             "efficiency_delta": e_open - e_sealed if e_open is not None and e_sealed is not None else None,
                             "rounds_delta": opened["rounds_played"] - sealed["rounds_played"]})
    metrics = {"planned": len(manifest["cases"]), "completed": len(completed),
               "failed_or_incomplete": len(failed), "pending": len(manifest["cases"]) - len(results),
               "saved_attempts": len(all_attempts), "dry_run": manifest["dry_run"], "usage_all_saved_attempts": usage,
               "conditions": condition_metrics, "role_metrics": role_metrics, "matched_chat_pairs": paired_rows,
               "matched_game_pairs": paired_games}
    (directory / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    # Shared document blocks produce readable Markdown and self-contained HTML.
    blocks = []
    def paragraph(title, text):
        blocks.append(("text", title, text))
    def table(title, headers, entries):
        blocks.append(("table", title, [headers, *entries]))
    label = "SCRIPTED DEMONSTRATION — NOT LLM RESULTS" if manifest["dry_run"] else "LIVE MODEL PILOT"
    paragraph("Experiment status", f"{label}. Planned: {metrics['planned']}; completed: {len(completed)}; "
              f"failed/incomplete: {len(failed)}; pending: {metrics['pending']}. "
              f"Saved attempts (including retries): {len(all_attempts)}.")
    paragraph("What was tested", f"Roles: two buyers and one seller. Assignment schedule: "
              f"{manifest['config']['assignments']}. Games: {', '.join(manifest['config']['games'])}. "
              f"Repetitions per configuration: {manifest['config']['repetitions']}. "
              "Open bids reveal the first buyer's move to the second; sealed bids do not. "
              "Chat off removes free-text messages but retains numerical seller asking prices.")
    table("Models", ["Alias", "Backend", "Requested model"],
          [[alias, a["backend"], a["model"]] for alias, a in manifest["config"]["agents"].items()])
    table("Scenarios (private experimenter values)", ["Scenario", *ROLES],
          [[s["name"], *[s["values"][r] for r in ROLES]] for s in manifest["config"]["scenarios"]])
    table("Condition outcomes", ["Game", "Scenario", "Chat", "Completed/attempted", "Agreement rate",
                                "Mean sale price", "Mean efficiency", "Efficiency n", "Mean rounds", "Invalid actions"],
          [[r["game"], r["scenario"], r["chat"], f"{r['completed']}/{r['attempted_cases']}",
            r["agreement_rate"], r["mean_price_if_sold"], r["mean_efficiency"], r["efficiency_n"],
            r["mean_rounds"], r["invalid_actions"]] for r in condition_metrics])
    paragraph("Reading these metrics", "Rates and efficiencies are fractions (1.0 = 100%). "
              "Outcome statistics use completed episodes only, including no-sale episodes. "
              "Mean sale price uses sales only. Failures are shown separately, never scored as no sale. "
              "Efficiency is N/A when no positive surplus is feasible. SD is a descriptive sample standard "
              "deviation, not a confidence interval. Aggregated role means mix scenarios/opponents; inspect "
              "players.csv for matched contexts. There is no overall model ranking.")
    table("Payoffs by model and role", ["Game", "Chat", "Role", "Alias", "n", "Mean payoff", "Sample SD",
                                        "Negative payoffs", "Invalid actions"],
          [[r[k] for k in ("game", "chat", "role", "alias", "n", "mean_payoff", "payoff_sample_sd",
                           "negative_payoffs", "invalid_actions")] for r in role_metrics])
    paired_groups = defaultdict(list)
    for row in paired_rows:
        paired_groups[(row["game"], row["scenario"])].append(row)
    table("Matched chat-on minus chat-off differences", ["Game", "Scenario", "Completed pairs", "Agreement delta",
                                                        "Efficiency delta", "A payoff delta", "B payoff delta", "Seller payoff delta"],
          [[g, s, len(group), *[mean([r[k] for r in group]) for k in
                                ("agreement_delta", "efficiency_delta", "buyer_a_payoff_delta", "buyer_b_payoff_delta", "seller_payoff_delta")]]
           for (g, s), group in sorted(paired_groups.items())])
    paragraph("Limits of the comparison", "Pairs match game, values, model assignment, buyer order, repetition, and budgets. "
              "Model outputs are stochastic; matching conditions does not match randomness. Partial batches can be "
              "unbalanced, and failures can bias completed-only summaries. A single repetition cannot establish "
              "a stable effect. Full role permutations vary opponent roles as well; these outcomes measure "
              "performance in this lineup, not intrinsic model ability. Profit alone does not establish exploitation "
              "or collusion. Codex model IDs are requested settings, not independently verified model snapshots.")
    game_groups = defaultdict(list)
    for row in paired_games:
        game_groups[(row["scenario"], row["chat"])].append(row)
    table("Matched open-bids minus sealed-bids differences", ["Scenario", "Chat", "Completed pairs",
                                                             "Agreement delta", "Efficiency delta", "Rounds delta"],
          [[s, chat, len(group), *[mean([r[k] for r in group]) for k in
                                   ("agreement_delta", "efficiency_delta", "rounds_delta")]]
           for (s, chat), group in sorted(game_groups.items())])
    multi = sum(r["rounds_played"] > 1 for r in completed)
    first_sales = sum(bool(r["trade"]) and r["trade"]["round"] == 1 for r in completed)
    paragraph("Interaction depth", f"{multi}/{len(completed)} completed episodes reached more than one round; "
              f"{first_sales}/{len(completed)} ended in a first-round sale. If most games end immediately, "
              "the pilot offers little evidence about adaptation across turns; consider a repeated-market game next.")
    paragraph("Usage", f"All saved attempts: {usage['attempted_requests']} player requests, "
              f"{usage['input_tokens']} input tokens, {usage['output_tokens']} output tokens. "
              "Unknown usage from interrupted/failed transports is excluded. Codex input totals include its "
              "agent runtime overhead and do not translate directly into subscription credits or dollars.")
    table("Failed or incomplete cases", ["Case", "Game", "Scenario", "Status", "Error"],
          [[r["case"]["id"], r["case"]["game"], r["case"]["scenario"], r["status"], r.get("error", "")]
           for r in failed])
    examples = []
    if completed:
        for r in [max(completed, key=lambda r: r["rounds_played"]),
                  min(completed, key=lambda r: r["allocation_efficiency"] if r["allocation_efficiency"] is not None else float("inf")),
                  completed[0]]:
            if r["case"]["id"] not in [e["case"]["id"] for e in examples]:
                examples.append(r)
    paragraph("Transcript examples", "Selected descriptively: longest negotiation, lowest defined efficiency, "
              "and first completed case, without duplicates. Read the full logs before making behavioral claims.")
    for r in examples:
        events = [json.loads(line) for line in (directory / r["_directory"] / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        case = r["case"]
        table(f"Observer setup for case {case['id']}", ["Role", "Model", "Private item value", "Final gain"],
              [[role, case["agents"][case["roles"][role]]["model"], case["values"][role], r["payoffs"][role]]
               for role in ROLES])
        paragraph(f"Outcome calculation for case {case['id']}",
                  f"Sale price: {(r['trade'] or {}).get('price', 'no sale')}. "
                  f"Actual total gain: {r['realized_surplus']}. Best possible total gain: {r['maximum_feasible_surplus']}. "
                  f"Allocation efficiency: {r['allocation_efficiency']:.1%}. "
                  "These private values and calculations are observer information, not extra information supplied to players."
                  if r["allocation_efficiency"] is not None else
                  "No positive total gain was feasible; efficiency is N/A. Private values above are observer information.")
        table(f"Case {r['case']['id']} — {r['case']['game']}, {r['case']['scenario']}, chat={r['case']['chat']}",
              ["Round", "Player", "Action", "Price", "Accept buyer", "Public message", "Valid"],
              [[e["round"], e["actor"], e["action"].get("action"), e["action"].get("price"),
                e["action"].get("buyer_id"), e["action"].get("message"), e["valid"]]
               for e in events if e["kind"] == "action" and isinstance(e.get("action"), dict)])
    paragraph("For the mentor meeting", "Bring the game rules, condition table, two annotated transcripts, "
              "and related-work notes. Discuss which interaction is worth studying, whether the game elicits "
              "enough adaptation, and how to introduce Duels-style authoring/counter-moves. "
              "This report describes observations; it does not establish research novelty or causal mechanisms.")
    paragraph("Provenance", f"Configuration hash: {manifest['config_hash']}. Engine/runner source hash: "
              f"{manifest['source_hash']}. manifest.json contains the exact expanded plan. "
              "episodes.csv contains latest attempts; episode directories retain all prior attempts. "
              "players.csv provides per-role values, payoffs, and usage; metrics.json includes individual matched pairs.")

    title = manifest["config"]["name"] + " — arena experiment"
    markdown = ["# " + title, ""]
    body = ["<h1>" + html.escape(title) + "</h1>"]
    for kind, heading, content in blocks:
        markdown.extend(["## " + heading, ""])
        body.append("<section><h2>" + html.escape(heading) + "</h2>")
        if kind == "text":
            markdown.extend([content, ""])
            body.append("<p>" + html.escape(content) + "</p>")
        else:
            headers, *entries = content
            def mdcell(c):
                return html.escape(fmt(c)).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
            markdown.extend(["| " + " | ".join(map(mdcell, headers)) + " |",
                             "| " + " | ".join("---" for _ in headers) + " |"])
            body.append("<div class='scroll'><table><thead><tr>" + "".join("<th>" + html.escape(str(c)) + "</th>" for c in headers) + "</tr></thead><tbody>")
            for entry in entries:
                markdown.append("| " + " | ".join(map(mdcell, entry)) + " |")
                body.append("<tr>" + "".join("<td>" + html.escape(fmt(c)) + "</td>" for c in entry) + "</tr>")
            if not entries:
                markdown.append("| " + " | ".join(["No data"] + [""] * (len(headers) - 1)) + " |")
                body.append(f"<tr><td colspan='{len(headers)}'>No data yet</td></tr>")
            markdown.append("")
            body.append("</tbody></table></div>")
        body.append("</section>")
    (directory / "report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    document = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>" + html.escape(title) + "</title><style>"
                "body{font:15px/1.6 system-ui,sans-serif;color:#182338;background:#f2f5fa;margin:0;padding:32px;max-width:1400px;margin:auto}"
                "h1{font-size:30px}h2{font-size:20px}section{background:white;padding:22px;margin:20px 0;border-radius:12px;border:1px solid #dce3ee}"
                ".scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #dde4ed;vertical-align:top}"
                "th{background:#edf2fa;white-space:nowrap}p{max-width:1100px}td{max-width:400px;overflow-wrap:anywhere}"
                "@media print{body{padding:0;background:white}section{break-inside:avoid}.scroll{overflow:visible}}"
                "</style>" + "".join(body) + "</html>")
    (directory / "report.html").write_text(document, encoding="utf-8")
    return metrics
