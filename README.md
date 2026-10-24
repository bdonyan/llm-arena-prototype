# Three-agent negotiation pilot

**Start with [NINE_GAME_RESULTS.md](NINE_GAME_RESULTS.md)** for the completed
nine-game pilot, worked payoff calculations, and limitations. Selected results
and transcripts for review are in `examples/nine-games/`. Raw development runs
remain local and are excluded from Git.

One seller and two buyers negotiate over one fictional item. Python is the
referee; Codex or a model API supplies each player's action. This is the standalone
gateway prototype for Track C, not yet an implementation of model-authored
environments or evidence of co-evolution.

## Configurable experiments and reports

Use **`3_agent_arena.py` for one game** and **`run_experiments.py` for a study**.
The experiment runner imports the same engine instead of duplicating game logic
or scraping command-line output. Configuration files specify the study:

| File | Role assignments | Games | Scenarios | Chat | Repetitions | Episodes |
| --- | --- | --- | --- | --- | --- | --- |
| `experiments/pilot.json` | 3 cyclic rotations | Sealed bids | 3 | On/off | 1 | 18 |
| `experiments/full.json` | All 6 permutations | Sealed + open bids | 3 | On/off | 1 | 72 |

The full grid covers every combination **of the factors in that configuration**,
not every possible model lineup or game. Its upper bound is 1,296 player
requests (72 episodes x 6 rounds x 3 players); many episodes may end earlier.
The pilot upper bound is 324. Codex runtime overhead can be substantial.

### Start here

Preview without model calls or file creation:

```sh
python run_experiments.py --config experiments/pilot.json --plan
```

Rehearse the entire workflow using scripted players and generate a sample report:

```sh
python run_experiments.py --config experiments/pilot.json --dry-run
```

Open `runs/experiments/pilot-scripted/report.html` in your browser. It is a local,
self-contained report. Scripted reports are explicitly labeled **not LLM results**.

Run the first matched chat-on/chat-off pair with real models:

```sh
python run_experiments.py --config experiments/pilot.json --run --limit 2 --max-requests 36
```

The sample models are `gpt-6-luna`, `gpt-6-sol`, and `gpt-6.1-sol`.
Only Luna was previously verified here in a live game. Other IDs are starting
configuration values, not a promise of account access. The runner stops on the
first failed episode so an unsupported model or exhausted allowance does not
produce a long batch of failures. Update model IDs to ones available to you.

After checking those results, complete the pilot:

```sh
python run_experiments.py --config experiments/pilot.json --run
```

Successful episodes are skipped on resume. Failures are retained and skipped
unless `--retry-failed` is added. A retry gets its own attempt directory; it does
not erase earlier evidence. Ctrl-C saves an aborted attempt. If the process was
forcibly killed, inspect the `.running` marker and remove it only after confirming
no runner is active. Do not run two processes against the same suite directory.

`--limit` and `--max-requests` apply to each invocation. The request cap reserves
an episode's worst-case requests before starting it; it caps player calls, not
transport retries, token usage, dollar spend, or included-plan credits. No batch
is executed unless `--run` or `--dry-run` is supplied.

### Change an experiment

Copy a JSON configuration and edit:

- `agents`: aliases mapping to `backend` (`codex` or `openai`) and exact `model` ID.
  Different backends may participate in one episode. API agents need an
  `OPENAI_API_KEY` environment variable; batch mode does not prompt for keys.
- `assignments`: `cyclic` or `all_permutations`. Roles are always two buyers and
  one seller. Each assignment uses all three aliases once.
- `games`: `sealed_bids`, `open_bids`, or both. In open bidding the second buyer
  sees the first buyer's current bid and message. The seller acts last in both.
- `scenarios`: named private valuations for `buyer_a`, `buyer_b`, and `seller`.
- `chat_modes`: `[true, false]` for the communication comparison.
- `repetitions`: independent repeats of each configuration; increase above one
  when the pilot works and the usage budget permits. Repeats are not seeded
  deterministic model calls.
- `rounds`: negotiation budget per episode.
- `buyer_orders`: optionally `[["buyer_a", "buyer_b"], ["buyer_b", "buyer_a"]]`
  to study action order, especially in open bidding. This doubles the grid.
- `codex_timeout`: per-move timeout. `max_output_tokens` affects API agents only;
  the Codex adapter currently fixes reasoning effort at `low`.

Always run `--plan` after changes. Use a different configuration `name` or
`--output-dir` for changed settings. Resume verifies configuration and engine
source hashes to avoid mixing experiments after implementation changes.

### Report contents

Every suite retains its expanded plan in `manifest.json`, a source snapshot, and
all episode attempts with `events.jsonl`, `summary.json`, and `console.txt`.
It regenerates these artifacts after every episode:

- `report.html`: readable offline report with tables and selected transcripts.
- `report.md`: equivalent Markdown report for meeting notes.
- `episodes.csv`: latest result per configuration, including failures.
- `players.csv`: model/backend/role, valuation, payoff, invalid actions, and usage.
- `metrics.json`: condition aggregates and individual matched chat comparisons.

The report separates model payoffs by role and game. It includes agreement rate,
conditional sale price, allocation efficiency, negotiation length, invalid
actions, negative payoffs, usage from **all** saved attempts, and explicit failure
counts. Aborted runs are excluded from outcome averages. Undefined efficiency
is not treated as zero. Matched comparisons require both conditions to finish.
One repetition gives preliminary observations, not a stable ranking or proof of
a communication effect. Opponents and roles affect outcomes. Partial batches
can be unbalanced; inspect counts before comparing models.

Rebuild a report without any model calls:

```sh
python run_experiments.py --report-only --output-dir runs/experiments/pilot-live
```

### Code boundaries

| Module | Responsibility |
| --- | --- |
| `3_agent_arena.py` | Small entry point for one episode |
| `arena_engine.py` | State, rules, actions, scoring, Codex/API adapters, single-game CLI |
| `experiment_config.py` | Configuration validation and experiment-grid expansion |
| `run_experiments.py` | Per-role model routing, execution, request caps, saved attempts/resume |
| `experiment_report.py` | Offline aggregation, comparisons, CSV/Markdown/HTML reports |

For another negotiation variant with the same action/payoff interface, extend
the game registry and its observation/transition behavior in `arena_engine.py`;
add visibility and scoring checks. For an unrelated domain (e.g., coalition
formation or repeated inventory trading), implement a new environment adapter
with its own legal actions, observations, termination, and summary metrics.
Changing only prompt text does not implement a new game. Model providers belong
in policy adapters, and new evaluation metrics belong in the environment summary
and report, rather than in the model prompts.

## Plan

1. Verify rules, accounting, and private observations using scripted players.
2. Connect three player roles to OpenAI models and run one short live episode.
3. Run matched chat/bids-only pilots, rotate models across roles, and bring
   transcripts plus payoff/efficiency results to Oscar and Robin.
4. Agree on the research hypothesis and integration with Environment Duels.

## Run without an API key

Requires Python 3.10+. No packages are needed for the scripted demonstration:

```sh
python3 3_agent_arena.py --dry-run
python3 3_agent_arena.py --dry-run --no-chat
python3 -m unittest discover -s tests -v
```

**Dry-run actions are scripted. They do not measure LLM capabilities.**

## Run Codex players using your ChatGPT login (default)

Codex CLI is already installed on this machine, and `codex login status` reports
ChatGPT authentication. You do not need a Platform API key for this mode.
The script searches your terminal PATH and then the native Codex binary bundled
with VS Code/Cursor extensions. You can run the arena even when your terminal
does not recognize the `codex` command. It prints the executable it finds.
For a custom location, set `CODEX_BINARY` to the full executable path.

```sh
codex login status
python3 3_agent_arena.py --rounds 1
```

If login is missing, run `codex login` and select ChatGPT sign-in. This uses your
Codex allowance, subject to your plan and model access. It is not unlimited.

For the full game or the bids-only comparison:

```sh
python3 3_agent_arena.py
python3 3_agent_arena.py --no-chat
```

The default model is `gpt-6-luna` for all three roles: this is a mechanics check
with three independent players. To compare different models, select exact model
IDs available to your Codex account using `--buyer-a-model`, `--buyer-b-model`,
and `--seller-model`. Account access is confirmed only by successful execution.

How it works:
1. Python passes one player's rules and private observation to `codex exec`.
2. Codex returns one JSON action constrained by `--output-schema`.
3. Python validates it and delivers permitted bids/messages to subsequent players.
4. Repeat until a sale or the round limit.

Each move uses a fresh ephemeral session with explicit public history. It does
not resume this coding conversation or another player's session. Sessions run
in temporary working directories, ignore user config, disable project
instructions, and disable shell tools, apps, plugins, memories, hooks, browsing,
and delegation. Observed command/MCP/search/file-change tool events abort the
episode. This is a controlled local pilot, not a hardened isolation system for
adversarial agents. Do not turn on tools that can read experimenter logs.

The adapter forces ChatGPT authentication and removes API-key environment
variables from child processes. It never copies or edits your credential files.
Codex itself can still maintain its normal local runtime databases.

There are at most three Codex sessions per round. CLI transport retries may
occur; `--codex-timeout` defaults to 180 seconds per move. The OpenAI-only
`--max-output-tokens` option does not cap Codex output. Codex token usage is
recorded when its CLI emits usage events; it does not represent a dollar bill.
Codex failures save diagnostic files and mark the run aborted.

## Run with a separately billed OpenAI API key (optional)

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python 3_agent_arena.py --backend openai
```

The program reads `OPENAI_API_KEY`, or prompts for a hidden key in an interactive
terminal. It never saves the key. Do not paste credentials into chat or source
files. The live run requires an API key with model access and API billing/quota.
This mode does not use your ChatGPT/Codex subscription allowance.

The default uses `gpt-4o-mini` for all three independent players to check that
everything works. To choose different OpenAI models, pass their exact API IDs:

```sh
.venv/bin/python 3_agent_arena.py --backend openai \
  --buyer-a-model gpt-4o \
  --buyer-b-model gpt-4o-mini \
  --seller-model gpt-4o-mini
```

All selected models must support the Responses API and Structured Outputs.
Availability depends on your account; labels from meeting notes are not
necessarily API model IDs. The API adapter calls OpenAI only.

The actual request is in `LivePolicy.choose` in `arena_engine.py`:
`client.responses.create(model=..., instructions=..., input=..., text=...)`.
The input contains only that player's permitted observation. A strict JSON
schema constrains the response; Python separately checks game legality.

In API mode at default settings there are at most 18 requests per episode, with at most
512 output tokens requested per call. Runs end on a sale. Automatic retries are
disabled. This bounds requests, not dollar cost; inputs include growing history,
and prices depend on the model. Usage is saved without a hard-coded price table.
Reasoning models may require a larger `--max-output-tokens` value.

## Game specification

- Buyers each start with 150 credits, no item, and a private item value.
- Seller starts with one item and a private reservation value.
- Default values are A=100, B=80, seller=40. Players are told only their own
  value and the common range [0,150], not these defaults.
- Each round both buyers bid from the same prior-round information. Calls are
  sequential, but neither sees the other's current bid/message before bidding.
- Seller sees both current bids and messages, then accepts one or rejects both.
- A rejected seller may suggest an asking price. This is advisory, not binding.
- Bids expire after the seller's decision. No borrowing, resale, or side payments.
- Six rounds maximum by default. `--rounds` changes this up to 20.
- Illegal actions count as pass/reject and are recorded. API failures, refusals,
  and incomplete/invalid JSON responses abort the episode and save an explicit
  aborted status. Aborted runs must not be scored as negotiation failures.
- Legal but unprofitable trades are allowed, so irrational decisions remain
  observable. The referee does not optimize an agent's actions for it.

## What to inspect

Each run creates `runs/<unique-run-id>/events.jsonl` and `summary.json`.
Logs contain private experimenter information and must not be shared with
players during play. They include model configuration, observations, actions,
trades, response IDs, returned model IDs, and token usage.

Buyer payoff is its private value minus payment if it wins, otherwise zero.
Seller payoff is sale price minus reservation value, otherwise zero. These are
economic utility changes, not simply changes in cash balances.

Maximum feasible surplus is `max(0, max(buyer values) - seller value)`.
Efficiency is realized surplus divided by that maximum, or N/A if the maximum
is zero. Harmful allocations can have negative surplus; this is not clipped.
The program does not infer coalitions or exploitation from individual outcomes.

## First comparison

Run a live chat episode and a matched bids-only episode:

```sh
python3 3_agent_arena.py
python3 3_agent_arena.py --no-chat
```

Here bids-only still allows the seller to announce a numerical asking price.
The treatment difference is free-text public messages.

Repeat for several value configurations, for example
`--buyer-a-value 70 --buyer-b-value 110 --seller-value 50`. Keep models, values,
round budgets, and token limits matched between conditions. Swap buyer/model
assignments and rotate models through seller roles. Seeds do not make API model
outputs deterministic; replay saved actions when auditing a particular episode.

Start with 5–10 runs per condition only if your usage allowance or API budget permits. Treat results
as exploratory. Report agreement rate, sale prices, per-role payoffs, allocation
efficiency, invalid actions, and usage. Bring two annotated transcripts and a
small results table to the next meeting. Discuss whether to study interaction
metrics or introduce model-authored scenarios/counter-moves next.

Official references:
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-4o mini capabilities](https://developers.openai.com/api/docs/models/gpt-4o-mini)
