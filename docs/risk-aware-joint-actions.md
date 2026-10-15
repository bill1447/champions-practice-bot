# Risk-aware joint-action candidate

`agent_v2.policy.decide_risk` is an explicit offline candidate. Public `decide`
uses baseline utility with a scoped joint tie-break for target allocation between
the same two immediate single-target attacks. See
`reviews/v2-coordination-2026-10-14.md` for its separate gameplay evidence.
The broader risk policy described here remains experimental; production search,
admission and fallback behavior remain unchanged. There is no native battle constructor, maintained hidden world,
seed or PRNG access in this evaluator.

The evaluator scores our complete joint command against plausible joint enemy
responses: attacks on either slot, either or both Protects, available public
support hypotheses, and preview-bench switches. Unrevealed Protect remains a
possibility even without ordinary learnset evidence. Response coverage is bounded
and does not establish which hidden moves or switches are actually legal.

Damage, conditional KO potential, capped damage, survival, order, retargeting,
friendly spread damage and field positioning are evaluated together. Protect,
switching, redirection, Tailwind, Trick Room and spread alternatives receive
candidate reservations before attack-heavy pruning. Owned request stats and move
targets are authoritative inputs; opponent stats and unknown attacks use broad
public species assumptions. The beam starts with 24 baseline-ranked commands and
adds reserved alternatives. Only complete response evaluations can rank a command;
deadline interruption retains a legal incumbent.

Opponent Protect response salience increases when our hypothesized concentration
looks lethal under a **public** forecast. That forecast clears our private stats,
items, abilities and unrevealed moves. It conditions on a candidate plan to explore
a robust counter-response; it does not claim the opponent observes our submitted
simultaneous command. Actual outcome estimates may use our legitimately owned data.

The score is 85% scenario-weighted mean utility plus 15% adverse utility. These
coefficients and response priorities are uncalibrated heuristics, not probabilities.
The model keeps low-salience Protect possible without automatically vetoing focus
fire. Telemetry retains top actions and focus/split/support representatives, their
conditional damage ranges, response parts, nominal and adverse utility, and
descriptive Protect exposure. It never labels a KO guaranteed or mechanics certified.

## Mechanical limits

The numeric ranges use simplified level-50 damage, stat ranges, roll padding,
priority and speed profiles. They are estimates, not mathematically valid bounds
over every hidden ability, item or lifecycle. Critical hits, many ability/item
effects, Mega stat transitions, two-turn moves, recoil, residual damage, status
durations, pivots, grounding exceptions and several support interactions remain
unmodeled. Successful repeated Protect and failed repeated Protect are separate
continuations after positive public Protect evidence; other stall variants need
their own controls. Unknown effects remain limitations rather than false exclusions.

Pinned native controls cover selected repeated Protect outcomes, Follow Me,
Surf partner damage, Bullet Punch order and Psychic Terrain blocking, and a second
normal attack retargeting after its selected foe faints. These establish selected
examples, not universal mechanical support. Unit controls additionally cover
decisive focus, low-salience Protect, split targeting, attack plus Tailwind, threatened
ally shielding/switching, strategic reservations and private-stat forecast isolation.

## Evaluation and reproduction

The frozen paired experiment uses PR #247's three unfamiliar compositions and four
seeds across two suites. Every agent/opponent case is side swapped with identical
teams, seeds and eight-second decision budgets. The baseline is unchanged V2,
not another run against the full production bot. Opponents are the preserved
pressure challenger and a related protective guard. The guard forecasts vulnerable
targets from public generic STAB exposure and chooses Protect more often on threatened
slots; it never receives our actual plan. It is a limited heuristic, not an independent
competitive player. No policy changes occur between the two frozen suites.

```powershell
python -m champions_practice.risk_joint_audit --seeds 2 --output runs/risk-joint-final
python -m champions_practice.risk_joint_audit --seeds 2 --seed-offset 2 --output runs/risk-joint-validation-final
python scripts/risk_joint_native_controls.py
python scripts/risk_joint_report.py runs/risk-joint-final/report.json runs/risk-joint-validation-final/report.json --output runs/risk-joint-analysis.json
```

Lossless compressed telemetry and paired analysis live in `reviews/risk-joint-248/`.
The source identity binds four changed runtime files to their baseline commit,
catalog and pinned simulator. Native controls and CI smoke run separately. CI
requires completion, pairing, legality and honest telemetry, not a win threshold.
Promotion requires broader independent opposition and investigation of retained
guard losses; this milestone does not authorize a production policy change.
