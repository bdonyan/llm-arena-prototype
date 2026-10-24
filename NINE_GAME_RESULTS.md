# Nine real-model games: results

**All nine games completed. These are real Codex model decisions, not scripted checks.**

The study used three requested model IDs: Luna (`gpt-6-luna`), Sol (`gpt-6-sol`), and Sol 6.1 (`gpt-6.1-sol`). Each model played each role once in each scenario. Every configuration was run once, with chat enabled and sealed bids. There was no chat-off comparison in this study.

## The accounting

The sale price is the credits transferred. Buyer gain = its private item value minus the price paid. Seller gain = sale price minus its private reservation value. A losing buyer earns zero. For example, in Game 1 the seller received 90 credits; its gain was 90 - 40 = 50. These are fictional game credits, not dollars.

**Private values were assigned by us in `experiments/nine_games.json`.** They are fixed game inputs, not amounts the models chose. Models chose the bids, messages, and accept/reject decisions. Each model saw its own value; you as the experimenter can see all three. Every saved `console.txt` in this nine-game study now includes an observer setup and a worked outcome calculation. These annotations were added from saved records without rerunning games or changing the original dialogue.

### What does 66.7% efficiency mean? Use Game 7

Imagine the item is a concert ticket. A values owning it at 80 credits, B at 100, and the seller values keeping it at 40. Those values are separate from their cash balances and their bids.

- **Best possible allocation:** B gets it. Moving the item from someone who values it at 40 to someone who values it at 100 creates 60 credits of total gain: `100 - 40 = 60`.
- **Actual allocation:** A got it for 80. A gained `80 - 80 = 0`; B gained zero because it did not buy; the seller gained `80 - 40 = 40`.
- **Efficiency:** the game realized 40 out of the possible 60 credits of total gain: `40 / 60 = 66.7%`.

There is no extra 20-credit payment missing from the records. The unrealized 20 is the additional value B would have received from ownership instead of A. Python knows the private values and can calculate this afterward; the seller did not know them.

If B had bought at a price of 80, B would gain 20 and the seller 40, totaling 60: 100% efficiency. If B paid 90 instead, B would gain 10 and the seller 50, still totaling 60. **Price divides the gains; ownership determines the available total gain in this simple game.**

Game 5 shows why efficiency is not enough: A's gain of 30 plus the seller's loss of 20 still totals the maximum available 10. The allocation was 100% efficient while the seller harmed its own objective. We record both measures.

## All nine outcomes

| Game | Scenario: values A/B/seller | Buyer A / Buyer B / seller models | Rounds | Winner | Sale price | A gain | B gain | Seller gain | Efficiency |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Clear gains: 100/80/40 | Luna / Sol / Sol 6.1 | 3 | A | 90 | 10 | 0 | 50 | 100.0% |
| 2 | Clear gains: 100/80/40 | Sol / Sol 6.1 / Luna | 1 | A | 55 | 45 | 0 | 15 | 100.0% |
| 3 | Clear gains: 100/80/40 | Sol 6.1 / Luna / Sol | 3 | A | 75 | 25 | 0 | 35 | 100.0% |
| 4 | Narrow gains: 70/65/60 | Luna / Sol / Sol 6.1 | 5 | A | 70 | 0 | 0 | 10 | 100.0% |
| 5 | Narrow gains: 70/65/60 | Sol / Sol 6.1 / Luna | 1 | A | 40 | 30 | 0 | -20 | 100.0% |
| 6 | Narrow gains: 70/65/60 | Sol 6.1 / Luna / Sol | 5 | A | 67 | 3 | 0 | 7 | 100.0% |
| 7 | Values swapped: 80/100/40 | Luna / Sol / Sol 6.1 | 3 | A | 80 | 0 | 0 | 40 | 66.7% |
| 8 | Values swapped: 80/100/40 | Sol / Sol 6.1 / Luna | 1 | B | 60 | 0 | 40 | 20 | 100.0% |
| 9 | Values swapped: 80/100/40 | Sol 6.1 / Luna / Sol | 1 | B | 99 | 0 | 1 | 59 | 100.0% |

Efficiency measures whether the item reached the buyer who values it most, relative to the maximum available total gain. It does not measure whether each participant benefited.

## Three observations to bring to the meeting

1. **We can observe negotiation across turns.** In Game 1, the seller asked for 90. Buyer A bid 72, then 81, then 90; the seller accepted in round three. These are observable responses over time, not proof that communication caused the improvement. Five of the nine games lasted more than one round.

2. **Efficient allocation can conceal an individual failure.** In Game 5, Luna as seller accepted 40 while its reservation value was 60. The seller lost 20, and the winning buyer gained 30. Total gain was still the maximum of 10, so allocation efficiency was 100%. This demonstrates why we need individual gains and loss counts alongside efficiency.

3. **Tied bids can change the allocation.** In Game 7 both buyers bid 80. The seller chose Buyer A, whose private value was only 80, while Buyer B valued the item at 100. Total gain was 40 rather than the possible 60: 66.7% efficiency. The seller could not see those private values, and the rules let it choose either tied bidder. This motivates examining tie handling and player-label effects; one example does not establish a bias.

## What we can and cannot conclude

- All 9 games reached a sale. There were 0 invalid actions and 0 failed episodes.
- The higher-value buyer won 8 of 9 games. One seller incurred a negative gain.
- Luna accepted the first offers in all three games where it was seller, including the losing trade. The buyer models also varied across assignments, so this is a pattern in these lineups, not an isolated model effect.
- One run per configuration cannot establish reliability or rank models. There were no repetitions, no chat-off control, and no two-player comparison.
- Models acted in fixed roles and rules. We did not test model-authored environments, counter-moves, learning between games, or co-evolution.
- Model IDs are requested settings through Codex, not independently verified version snapshots. Every move used a fresh session with its permitted game history.

## Proposed meeting discussion

Present the game rules and this table, then read Games 1, 5, and 7 as concrete examples. Ask Oscar and Robin:

1. Does this interaction capture the intended Arena direction?
2. Should we investigate failures to protect private utility, adaptation across turns, or allocation/tie handling?
3. Which observations should we repeat under controlled role/opponent settings?
4. How should this connect to the Duels authoring-and-counter-move framework and group infrastructure?

We now have preliminary observations to discuss; this is not yet evidence of a novel benchmark or a general model ranking.

## How the code runs one game

1. **Choose the inputs.** `experiment_config.py:load_config` reads the JSON, and `expand_cases` lists the nine combinations. These assign values and models to roles; they do not decide how agents play.
2. **Create the world.** `run_experiments.py:execute_episode` calls `arena_engine.py:create_arena`. It creates the seller's item and each buyer's 150-credit balance.
3. **Ask for moves.** `arena_engine.py:play` calls `Arena.observe` to construct each player's permitted information. `RoutedPolicy.choose` selects its provider; `CodexPolicy.choose` sends that observation plus game rules to a fresh Codex session and receives JSON. Both buyer observations are prepared before bidding, so neither sees the other's current bid.
4. **Apply the rules.** `Arena.validate` checks legality. The seller sees current bids and chooses a bidder or rejects both. `Arena.settle` transfers credits and ownership after acceptance. The referee permits unprofitable but legal decisions; it does not play on the agent's behalf.
5. **Score and save.** `Arena.summary` calculates individual gains and efficiency from the final state and private values. The journal saves actions/outcomes, and `experiment_report.py` makes the readable report. Observer explanations are printed for you, never added to `Arena.observe` or sent to players.

`3_agent_arena.py` is just the entry point for a single episode. The batch runner uses the same engine. You do not need to understand the reporting code to understand the game; start with `Arena.observe`, `play`, `Arena.settle`, and `Arena.summary` in `arena_engine.py`.

## Usage and evidence

The nine games used **69 player requests**, with 763,328 reported input tokens and 5,919 output tokens. The Codex input total includes its agent-runtime overhead; it is not a separate dollar bill and does consume subscription allowance. No extra live games were run beyond these nine.

- [Study configuration](experiments/nine_games.json)
- [Detailed HTML report](examples/nine-games/report.html)
- [Results table as CSV](examples/nine-games/episodes.csv)
- [Exact plan and provenance](examples/nine-games/manifest.json)

- [Game 1 terminal transcript](examples/nine-games/game-1.txt)
- [Game 5 terminal transcript](examples/nine-games/game-5.txt)
- [Game 7 terminal transcript](examples/nine-games/game-7.txt)
