# Independent-opponent evaluation and next loss-review target

PR #249 remains frozen at `e0ae723`; its branch was not modified. This evaluation
lives separately on `evaluation/independent-opponents`. No gameplay policy was tuned.

## Opponent selection

The installed **poke-env 0.16.1 SimpleHeuristicsPlayer** provides an independently
implemented doubles control. Its policy uses matchup, stat-ratio, health, switching
and attack heuristics. It does not call V2's utility, joint evaluator or learned model.
Its decision methods are imported without editing them. Package version and source
SHA-256 are frozen in the manifest.

Compatibility research:

| Candidate | Finding | Disposition |
| --- | --- | --- |
| [poke-env baselines](https://github.com/hsahovic/poke-env/blob/master/src/poke_env/player/baselines.py) | Installed implementation supports doubles; can be called offline without creating a Player client | Selected first control |
| [Foul Play](https://github.com/pmariglia/foul-play) | Its README specifies singles support | Not a drop-in doubles opponent |
| [VGC-Bench](https://github.com/cameronangliss/vgc-bench) | Doubles benchmark with heuristic and learned agents; pinned environment, action/state representation and checkpoint compatibility require further audit | Learned agents deferred; its documented heuristic family is represented by the installed baseline |
| [EliteFurretAI](https://github.com/caymansimpson/EliteFurretAI) | VGC project with supervised/RL work; no compatible local checkpoint was established in this investigation | Not counted as an evaluated opponent |

This control is **not a proven competitive bot**. In particular, the upstream
heuristic normally does not choose Mega evolution. No Mega augmentation was added.
Its stat-ratio/damage heuristics remain approximate; adapting static data does not
make its evaluation mechanically exact.

## Closed-information, offline adapter

The adapter receives only its own sanitized view and authoritative legal menu. Owned
requests supply its actual HP, stats, items, abilities and moves. Opponent objects
contain public species, displayed HP fraction, boosts and status. Injected opponent
stats, exact HP, moves, items, abilities, hidden roots and battle RNG are ignored.
Public displayed HP is represented fractionally, not mistaken for exact native HP.

Species types/base stats and move data come from a separate read-only export of the
pinned Champions Dex. This handles Champions forms without silently substituting
vanilla species data. All 324 ordinary type matchups match poke-env's Gen-9 chart.
This is a bridge for this heuristic's inputs, not certification of a general-purpose
external player adapter for every lifecycle or type-changing effect.

The bridge creates no websocket client, account or online battle. Only poke-env's
local asyncio infrastructure initializes. Opponent policy randomness has a separate
seed and preserves Python's ambient random state. It never receives the battle RNG
or the other policy's submitted action. Unknown/default or illegal upstream orders
use an explicitly logged, seeded random legal fallback. No V2 scorer repairs them.

Both compared V2 policies, including their joint dependencies, are loaded into
separate frozen namespaces: pre-PR `567556a`, post-PR `e0ae723`.

## Frozen experiment

Six six-Pokémon compositions cover rain/grass, ground/pivot, psychic/room, sand/pivot,
Armarouge support and grass balance. There are three matchups, eight initial seeds,
both policy/team assignments, and actual **team-preserving p1/p2 reversals**. Selected
four and lead order alternate between `1234` and `1324`. Familiar species and one
previously exercised selected-four group remain; this is new matchup/opponent
evidence, not an untouched team or species-generalization holdout.

Cases, teams, policy source identities, external source identity, simulator revision
and eight-second budgets were frozen before games. There are 192 complete games:
96 pre/post pairs grouped into 48 mirrored seed/team cases. Mirror and seed outcomes
are correlated and must not be treated as 96 independent strength samples.

| Evidence | Pre-PR V2 | PR #249 V2 | Post-only / pre-only wins |
| --- | --- | --- | --- |
| All 96 pairs | 46/96 | 48/96 | 2 / 0 |
| Exclude any pair with external fallback | 40/88 | 42/88 | 2 / 0 |

The two discordant wins are side reversals of **one underlying seeded case**. Its
first change replaces no-terrain Steel Roller with Earthquake. This supports a
specific mechanical correction; it does not demonstrate transfer of the coordination
gain observed against our related pressure/guard policies. Nor does the small result
prove that the coordination rule is generally ineffective.

The final run includes 1,310 V2 submissions and 1,310 opponent submissions, including
forced waits. All are legal, with zero recorded ranking deadline exhaustions or
eight-second budget overruns. There are ten external fallbacks, all in replacement
phases (two in pre-PR games, eight post-PR), affecting eight matched pairs. The clean
pair result is reported separately rather than hiding or scoring away these cases.

Per controlled team, post-PR wins are rain/grass 16/16, ground/pivot 0/16,
psychic/room 2/16, sand/pivot 16/16, Armarouge support 2/16 and grass balance 12/16.
These strong matchup asymmetries show why the aggregate 50% is not a general rating
or a statement that the policies have equal strength. Team selection is fixed, not
the bot's own preview policy.

An initial 96-game unmirrored run and four-game smoke were development/readiness
checks. They are not pooled into the final counts. No sealed final holdout was used.

## Next concrete decision defect

In saved case `1-0-p1-post249`, Indeedee and Gardevoir face Tyranitar and Excadrill.
V2 selects Psychic plus Mega Mystical Fire. Excadrill's Iron Head knocks out Gardevoir
before its attack executes. Tyranitar uses Crunch into Indeedee. This is a lead for
reviewing action order and survival, including weather and Mega/ability transitions.
The actual hidden stats/ability are not knowledge available to V2.

After sealing those actions, an isolated native diagnostic compares legal alternatives
against the same recorded enemy response with eight coupled future seeds:

| Own joint action | Own survivors | Opponent survivors |
| --- | --- | --- |
| Selected Psychic + Mega Mystical Fire | 3 in all eight samples | 4 in all eight |
| Trick Room + Mega Protect | 4 in all eight | 4 in all eight |
| Psychic + Mega Protect | 4 in all eight | 4 in all eight |
| Follow Me + Mega Mystical Fire | 3 in all eight | 3 in five samples, 4 in three |

These are bounded, conditional one-turn counterfactuals using the actual archived
native state after decisions. No oracle snapshot feeds a policy or is persisted.
They are not win probabilities, exhaustive opponent coverage, or proof that Protect
wins the game. They do establish a reproducible missed defensive alternative.

Next hypothesis: the scorer overvalues attacks that a plausible faster threat can
prevent from executing. Test a narrow survival/defense intervention with adjacent
counterexamples where attacking or sacrificing is better. Do not add a universal
Protect bonus or increase Trick Room utility simply to memorize this opening.

## Validation and reproduction

Four critical adapter controls pass: private-input invariance/RNG isolation, side
symmetry, Champions base-stat fidelity with authoritative owned stats, and explicit
legal fallback. Full suite: **1,682 tests pass**. Ruff, JS syntax and whitespace
checks pass. Cold simulator integrity verification initially exceeded its default
startup allowance; the evaluation allows 60 seconds for startup while retaining
the checks and eight-second gameplay budgets.

The JSON companion validates case completeness, source/team identities, mirrored
pairing, legality, fallback accounting and type chart parity, and retains native
counterfactual scalars. Raw choosing-side traces and the pre-game manifest remain in
ignored local `runs/independent-opponents/side-swapped-v1/`.

```powershell
$env:PYTHONPATH='src'
../champions-practice-bot/.venv/Scripts/python.exe scripts/independent_opponent_evaluation.py --mirror-teams --seeds 8 --output runs/independent-opponents/side-swapped-v1
../champions-practice-bot/.venv/Scripts/python.exe scripts/independent_opponent_report.py runs/independent-opponents/side-swapped-v1/games.json.gz --native-witness --output reviews/independent-opponents-2026-10-15.json
```

Exact package and raw-file hashes are recorded. Changed upstream code or checkout
line endings require an explicit new identity, not silently treating a later run as
the same frozen experiment. No remote battle, training job, PR edit or push occurred.
