# V2 target coordination: adopted scoped tie-break

V2 now resolves some equally scored target allocations with the existing approximate
joint-response evaluator. The change fixes the reviewed split-versus-focus decision
and improves results on two paired gameplay suites. It is enabled in V2's public
`decide` entry point. The broader risk policy and production belief-search bot are
not enabled or modified by this change.

## Scope and rationale

The baseline scores each attack independently. In the reviewed turn-two position,
Dragon Claw into Archaludon plus Psychic Fangs into Basculegion ties concentrating
both attacks into Basculegion at 24.75 utility. The baseline chooses by menu order.
Native counterfactual controls showed a missed knockout; the joint evaluator prefers
concentration in this position (-20.874 versus -46.237 approximate utility).

The new rule compares only exact top-utility ties with the same two immediate,
single-target damaging moves and the same Mega choices. It may redistribute those
targets; it cannot choose a lower baseline score, substitute moves, switch, or add
support actions. Spread attacks, charging moves, variable-power moves and moves
with native `onModifyMove` callbacks are excluded. The public catalog exposes charge
and move-modification flags from the pinned Dex; request target classes are also
respected. Neither flag is a universal mechanical support certificate.

Existing joint estimates include coupled attacks, approximate order, retargeting,
survival, and hypothetical Protect responses. All eligible tied actions must finish
evaluation before the incumbent can change. An incomplete secondary comparison
keeps the baseline choice. Public telemetry retains primary utility separately from
the conditional joint analysis, and elapsed time includes the secondary evaluation.

No hidden simulator state, actual enemy submitted command or battle RNG enters the
policy. There is no new belief framework, training job or tactical search engine.

## Frozen gameplay evidence

Comparator: V2 including the Steel Roller repair at `9cca093`. Both opponents use
that same frozen scorer, so they do not inherit candidate changes. Each pair uses
the same teams, initial seed, player side and eight-second decision budget. Paired
starting seeds do not imply identical future random draws after actions diverge.

| Suite | Opponent | Baseline wins | Candidate wins | Candidate-only / baseline-only |
| --- | --- | --- | --- | --- |
| Existing compositions; eight new seeds | Pressure | 17/48 | 24/48 | 7 / 0 |
| Existing compositions; eight new seeds | Guard | 23/48 | 30/48 | 7 / 0 |
| New recombinations; four new seeds | Pressure | 10/24 | 13/24 | 3 / 0 |
| New recombinations; four new seeds | Guard | 14/24 | 15/24 | 1 / 0 |

All 288 games completed: 144 baseline and 144 candidate. There are 18 candidate-only
wins and no baseline-only wins in these suites. Twenty-two pairs have a first action
change at an identical choosing-side public view. All 2,541 submitted decisions are
legal, with zero recorded budget overruns or primary deadline exhaustions. Neither
policy selected Steel Roller without terrain in these runs.

On the original compositions, all gains come from the ground-spread/rain matchup
family. The new suite changes leads and partners using steel balance, reordered rain
and reordered psychic teams; it supplies four further candidate-only wins. These
are related synthetic opponents and familiar species, not independent competitive
opponents. Repeated matchups, seeds and policies are correlated; the 18 discordances
must not be treated as 18 independent demonstrations of general strength.

Candidate decision latency on existing compositions: median 0.347 ms, p95 1.466 ms,
maximum 7.172 ms. On new recombinations: median 0.561 ms, p95 4.031 ms, maximum
21.148 ms. These are measured samples, not worst-case latency guarantees.

After enabling the public entry point, all 1,274 candidate choosing-side views were
replayed through public `decide`. Every selected action matches the tested candidate,
and every selection has maximal primary baseline utility. This verifies the routing
change; it is not an additional gameplay sample. The machine-readable companion
binds tested and current source identities, catalog, archives and comparison counts.

## Controls and limits

Nine added cases cover exact-tie-only behavior, the public entry point, a Protect
counterexample favoring split targeting, combined knockout potential favoring focus,
incomplete comparison, expired deadlines, and rejection of charge/spread/dynamic
move families. Existing native controls pass for repeated Protect success/failure,
redirection, spread damage, priority/terrain interactions and retargeting. The full
suite passes 1,678 tests; Ruff, JavaScript syntax and whitespace checks pass.

The retained evaluator has approximate damage, opponent stat assumptions and
uncalibrated scenario weights. Ability/item effects, Mega transitions, status and
many move interactions remain limitations. Charging moves are excluded on our side;
opponent two-turn commitments are not yet modeled explicitly. The original native
witness benefits from a public commitment, but this change does not claim to infer
that commitment or prove the opponent cannot Protect or switch in general.

Earlier unrestricted tie experiments were development only. Reviewing their spread
and dynamic-target comparisons led to the scope exclusions before the reported
eight-seed/new-team runs. Their results are not pooled into the table. No model or
scoring coefficients were tuned during the final scoped suites. No sealed final
holdout was accessed. All raw traces remain in ignored local `runs/`.

Adoption is a measured V2 improvement on these conditions, not certification of
competitive play. The historical comparator remains available in Git. Next evaluate
independently implemented opposition and review remaining losses, particularly the
rain-side move-timing/boost interaction. Do not widen the tie-break's scope simply
because this limited version improved these matches.

## Reproduction

From the repository root, using the existing environment:

```powershell
$env:PYTHONPATH='src'
../champions-practice-bot/.venv/Scripts/python.exe scripts/v2_repair_gameplay.py --baseline 9cca093 --candidate coordination --seeds 8 --seed-offset 10 --output runs/v2-coordination/frozen-scoped
../champions-practice-bot/.venv/Scripts/python.exe scripts/v2_repair_gameplay.py --baseline 9cca093 --candidate coordination --team-suite recombined --seeds 4 --seed-offset 20 --output runs/v2-coordination/recombined
../champions-practice-bot/.venv/Scripts/python.exe scripts/v2_coordination_report.py runs/v2-coordination/frozen-scoped/games.json.gz runs/v2-coordination/recombined/games.json.gz --output reviews/v2-coordination-2026-10-14.json
```

Exact raw-file hashes may vary with checkout line endings; baseline source is read
directly from Git and action parity is checked independently of those file hashes.
