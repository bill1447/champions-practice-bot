# PR #248 — risk-aware joint-action evaluation

## Verdict

The candidate implements joint response evaluation without hidden-world reconstruction.
It improves against pressure in this small experiment but does **not** establish an
improvement against the protective guard. Keep it offline. Public `decide`, production
search and all admission safeguards remain unchanged.

## Frozen gameplay evidence

| Opponent | Baseline V2 | Risk candidate | Paired discordant results |
| --- | ---: | ---: | --- |
| Pressure | 9/24 (37.5%) | 14/24 (58.3%) | 5 candidate-only wins, 0 baseline-only |
| Protective guard | 12/24 (50.0%) | 11/24 (45.8%) | 4 candidate-only wins, 5 baseline-only |

First suite: pressure 4/12 baseline versus 6/12 candidate; guard 6/12 each.
Additional seeds, unchanged source: pressure 5/12 versus 8/12; guard 6/12 versus 5/12.
All 96 games completed. The two agents contribute 48 games each; 48 paired cases
use identical teams, seeds, side and eight-second budgets. Three held-out team
compositions, four seeds and both sides are exercised. This comparison is against
the unchanged V2 baseline, not the full production bot or an independent strong AI.

Baseline decisions: 467. Candidate decisions: 561. All 1,028 submitted decisions
were legal; zero deadline exhaustions or budget overruns. Candidate pressure latency
p50/p95/max is 13.5/94.7/163.3 ms; guard is 13.2/100.0/126.9 ms. The candidate is
slower than the sub-2-ms baseline but within the tested budget. There is no native
admission/fallback in this policy; deadline-incumbent use is 0/561 (0%).
Replaying all 1,028 stored choosing-side views through `origin/main`'s V2 policy
and this branch's baseline produced identical selected actions and top ranking scores.

The guard actually chose Protect in 95 candidate-game decisions versus 67 baseline-game
decisions. Those counts have different game lengths and are descriptive, not a causal
or probability estimate. Its public vulnerability forecast never receives our actual
command. It shares primitive scoring with V2 and remains a limited synthetic opponent.
The guarded result is a useful negative control against claiming robust improvement.

## Implementation and controls

Response evaluation is fundamental to command scoring. It estimates combined damage,
order, retargeting, survival and field position under complete opponent joint responses,
then combines weighted scenario utility and adverse utility. Focus, split, shielding,
switching, speed control, redirection and spread alternatives share that evaluator.
Protect priority responds to the public threat of a hypothesized concentrated plan;
private owned stats/items/abilities do not affect that forecast. Priorities and score
coefficients are explicitly uncalibrated, and no KO is marked mechanically guaranteed.

1,661 tests pass (main's 1,641 plus 16 policy/adapter controls and four paired-report
controls). Ruff and JavaScript syntax checks pass. Separate unrelated replay-inventory
work in the shared checkout was excluded from this PR and test count.

Selected pinned native controls pass: repeated Protect succeeds and fails across eight
opening seeds; Follow Me preserves its partner; Surf does 99 partner HP damage within
the conditional 68.8–121.4 estimate; Bullet Punch acts before normal attacks and is
blocked on grounded foes by Psychic Terrain; a second normal attack retargets the surviving
foe after the selected target faints. Unit scenarios cover decisive focus, Protect-driven
split/support preferences, low-salience Protect allowing focus, threatened ally defense,
priority/redirection/spread separation and candidate reservations for each slot.

These are selected mechanical controls, not full support certification. Ability/item
effects, Mega transitions, critical hits, residual effects, status durations, pivots,
grounding exceptions and several support interactions remain model limitations.
See `docs/risk-aware-joint-actions.md` for scope and reproduction commands.

## Artifacts and next gate

`risk-joint-248/analysis.json` validates source identity, complete pairs, legality,
budget telemetry and certainty flags directly from rows. `suite-1.json.gz` and
`suite-2.json.gz` preserve full public/owned decision inputs, response matrices and
opponent diagnostics losslessly; checksums are in the analysis. Native controls are
preserved separately. Runtime source identity is
`a129592a2c241990ccdd652c1b7c210ef94528fae5215bc7518379fc8324647a`, bound to baseline
`dccbe8ce006f15a8ad626e0b2da59194c663b5d1` and the pinned engine. No policy tuning
occurred between these final suites. Earlier development trials are not frozen results.

CI independently schedules native controls, an eight-game side-swapped smoke against
both opponents, and paired telemetry validation, using the existing prerequisite guard.
Local success does not establish GitHub CI success.

Next diagnose the five guard pairs where baseline wins and candidate loses: distinguish
damage/order approximation, candidate pruning, response generation and risk weighting
before tuning. Then repeat on independent guard policies and additional held-out teams.
Do not promote from the pressure improvement or conceal the guard regression.
