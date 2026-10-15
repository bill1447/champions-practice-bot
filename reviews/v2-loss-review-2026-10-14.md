# V2 gameplay reset: first loss review

Work starts from main `567556a`, on `improvement/v2-loss-review`.
The historical V2 comparator is preserved; the working V2 scorer now contains the
scoped Steel Roller repair below. Production belief-search configuration is unchanged.

## Local research isolation

Uncommitted replay-learning work (three modified tracked files and 60 untracked
files) is preserved in the local Git stash named
`Sequestered replay-learning research before V2 gameplay reset 2026-10-14`.
Its base branch `feature/regulation-replay-learning` remains available.
Ignored environments, runs, reference sources and external corpora were not moved.
Nothing was pushed. Restore the stash only on its original branch, after preserving
any new work; do not apply it onto the gameplay branch. The parent workspace README
is also a local research artifact outside this Git repository.

## Evidence reviewed

The frozen October 12 competitive archive contains 30 V2 games against the related
pressure challenger, with 11 wins and 19 losses. Thirteen losses contain 18 bounded
conditional material-dominance flags. These flags compare fixed opponent commands
and two sampled futures; they are leads, not optimal-action labels or proof of why
a game was lost. Repeated positions across seeds are correlated.

Reproduce the extraction from the repository root:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/v2_loss_review.py --archive reviews/competitive-evaluation-2026-10-12.json.gz --output runs/v2-loss-review/steel-roller-witnesses.json
```

The generated local evidence retains choosing-side views, legal menus, rankings and
existing bounded diagnostics. It binds the archive and historical policy by SHA-256.
Bulk witnesses stay in ignored `runs/`; only the extraction script and this review
belong in the proposed diff. No final replay or gameplay holdout was accessed.

## First selected defect: unconditional Steel Roller attack utility

V2 selects Steel Roller with no active terrain in 17 decisions across five losses.
The scorer treats its 130 base power as ordinary immediate attack utility and does
not check its terrain requirement. The pinned Showdown `data/moves.ts` implementation
at `steelroller.onTry` returns false with no terrain. A legal menu entry therefore
does not establish that the move will succeed.

In `pressure-2-4-p1-v2`, checkpoints 4 through 9 (turns 3 through 8), V2 repeatedly
selects Steel Roller against Garchomp. By turn 4 Garchomp has 1% visible HP. The
retained diagnostics prefer the otherwise identical Psychic Fangs alternative on
both sampled futures. Checkpoints 6 onward have a fainted partner and `pass`, so
there is no own partner action establishing terrain. These are particularly clear
cases for a native reproduction. They still do not establish that one correction
wins the whole game.

Hypothesis: withholding ordinary damage credit from Steel Roller when public terrain
is absent will stop these wasted attacks without requiring hidden-state inference.
Before implementing, account for terrain entering before execution (including a
switch that activates a terrain ability); terrain present now also does not guarantee
it survives until execution. Keep all commands legal and available. Do not globally
ban the move or claim guaranteed failure solely from the start-of-turn field.

## Other leads, deliberately separate

1. Five ground-spread losses repeat an equal-score split-versus-focus decision:
   Dragon Claw into Archaludon plus Psychic Fangs into Basculegion ties concentrating
   both on Basculegion. Existing conditional diagnostics favor concentration. This
   needs response-aware review, not a universal focus bonus.
2. Five rain-side losses repeat Dragon Pulse plus Phantom Force where a retained
   Electro Shot alternative improves conditional material. Charge turns, rain and
   delayed attacks need mechanical review before attributing this to valuation.

Four other losses have no existing material flag. Absence of a flag is not evidence
of correct play: the diagnostic only tests a few alternatives for one turn.

## Next bounded experiment

First reproduce the no-terrain witness and nearby terrain-present/terrain-entering
controls in the pinned native engine. Then implement one isolated scoring correction
with the historical V2 retained as the comparator. Check public-input decisions,
legality and relevant mechanical controls, followed by paired development games
against pressure and guard. Freeze the candidate before fresh gameplay evaluation.
Do not promote based on these reused losses or replay prediction accuracy.

The existing risk-aware candidate is already on main but remains experimental; its
pressure gain and mixed guard results do not justify enabling it during this repair.

## Steel Roller repair and measured result

The scorer now withholds Steel Roller's damage utility when terrain is absent and
the own joint command contains no possible terrain-setting action. The legal command
is retained. Named and numeric moves are handled. Existing terrain, a planned terrain
move, or a switch into a known Surge ability retains provisional credit; a switch
with unknown own ability also remains possible. None of these cases certifies order,
survival, ability activation or what the opponent will do.

`scripts/steel_roller_native_controls.py` passes four pinned-native controls: no
terrain causes zero damage; Psychic Terrain allows damage and is removed; repeating
the attack after removal causes no further damage; switching Indeedee in before the
attack establishes terrain and permits damage. Eight added unit cases cover the
scoring and named/numeric joint-plan behavior.

`scripts/v2_repair_gameplay.py` ran 96 complete development games, preserving the
baseline scorer from Git `567556a` and cloning pressure/guard functions with that
same frozen scorer. Opponents therefore do not inherit the candidate repair. Three
existing compositions, four new deterministic seeds and both sides give 24 matched
cases per opponent, each with baseline and candidate runs at eight-second budgets.

| Opponent | Frozen V2 | Repaired V2 | Candidate-only / baseline-only wins |
| --- | --- | --- | --- |
| Pressure | 8/24 | 8/24 | 0 / 0 |
| Guard | 12/24 | 12/24 | 0 / 0 |

All 943 decisions were checked against authoritative public menus, with zero deadline
exhaustions or budget overruns. Baseline selected no-terrain Steel Roller 74 times
across 16 games; candidate did so zero times. Sixteen matched cases have a first
action divergence at an identical observed state. No winners changed. Counts across
divergent trajectories are descriptive, not 74 independent causal improvements.

Conclusion: the mechanical valuation error is repaired, but this experiment shows
no playing-strength gain. Keep that distinction explicit. Full public/owned traces
and source hashes remain local in `runs/v2-loss-review/steel-roller-gameplay/`.

Reproduce:

```powershell
$env:PYTHONPATH='src'
../champions-practice-bot/.venv/Scripts/python.exe scripts/steel_roller_native_controls.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/v2_repair_gameplay.py --seeds 4 --output runs/v2-loss-review/steel-roller-gameplay
```

## Continued review: target coordination and public move commitments

`scripts/v2_targeting_controls.py` recreates two archived turn-two positions by
replaying their complete prefixes, checks exact public-view equality, then evaluates
the selected command and retained alternative with eight coupled future seeds.
Native snapshots are diagnostic-only and never enter the policy. Opponent Protect
variants are tested only if present in the authoritative menu for that actual state.

For `pressure-0-0-p1-v2`, split Dragon Claw/Psychic Fangs and concentration into
Basculegion have identical V2 utility (24.75). Concentration leaves two opponent
survivors instead of three on all eight futures, with the same own survivor count,
against both the recorded response and the legal Archaludon-Protect variant. Protect
variants for Basculegion are unavailable in this state: its two-turn move commitment
matters. This supports investigating joint damage and public commitments rather than
rewarding all concentrated attacks indiscriminately. Total opposing remaining HP
does not always decrease, so these are material comparisons, not utility proofs.

For the mirrored rain-side lead, Electro Shot plus Phantom Force removes an extra
opponent compared with Dragon Pulse plus Phantom Force across all eight futures in
each of four legal response contexts, without changing own survivor counts. The
native Electro Shot implementation boosts Special Attack before hitting in rain;
Phantom Force has a charging/commitment phase and bypasses Protect on its hit. The
baseline power/type proxy models none of those interactions explicitly.

These samples condition on the archived actual hidden sets and are not calibrated
win probabilities or general policy labels. Next separate public-information
coordination from hidden-stat dependence and test nearby Protect/overkill/order
counterexamples before choosing another scoring change. No focus bonus or two-turn
heuristic has been enabled as part of the Steel Roller repair.

Validation: 1,669 tests pass, including 53 directly relevant policy/evaluation tests;
native Steel Roller controls pass. Full-suite collection initially stalled in
`poke_env`'s local asyncio socket-pair creation under the sandbox; the unchanged test
command passed outside the sandbox. No source workaround was introduced for that.
