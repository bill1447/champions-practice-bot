# Team and opponent-policy coverage

Run `.venv/Scripts/python.exe -m champions_practice.diversity_league --budget 8`.
The matrix runs nine sealed production-bot games: three synthetic opponent
rosters crossed with attack-first, seeded mixed-command and support/switch
policies. Own rosters rotate across cells too. Balance, rain and sand contain
13 distinct species; each roster is validated against the pinned Champions M-C
format. Teams, the fixed public prior catalog, policies, seeds, budgets, source
fingerprint and Showdown revision are bound into the report identity.

These sets are explicit synthetic fixtures, not external metagame priors or
opponent truth derived from a live battle. Policies see only request-derived
legal command strings, avoid deliberate ally attacks, and receive no bot action,
private world or native state. One seed per cell is initial coverage, not a
strength estimate or causal comparison of policies. Varying own rosters means
policy differences must not be read as controlled strength comparisons.

Reports under `runs/diversity-league/<id>/` retain per-decision public checkpoints,
mode, action, particle/candidate/branch counts and native admission telemetry.
Telemetry contains counts and bounded reasons only: attempted roots, generated
native candidates, independently positive matches and admitted particles.
Unsupported and rejected construction never grants hidden-world exclusion.
Opening decisions are labeled as openings without present-state admission;
forced waits explicitly require no admission. Counts describe bounded proposals,
not an exhaustive opponent distribution or historical RNG witnesses.

A failed sealed command is retained as a failed cell and its last public
checkpoint, rather than counted as a completed loss. The runner continues other
cells so one failure cannot hide untested matchups. Completed-game rates exclude
failed cells, which must always be reported alongside them.

Audit existing saved reports with
`.venv/Scripts/python.exe -m champions_practice.admission_audit <report> ...`.
This reconciles modes, branch totals and public legality, then independently
reconstructs every saved midgame action checkpoint from public evidence.
Reports under `runs/admission-audit/<original-id>/` bind the audit source and the
original source separately. Missing original admission telemetry stays marked
`not-recorded`; offline reconstruction is not relabeled as original runtime
telemetry and does not reproduce the original wall-clock admission deadline.

Matching native projections remains a necessary check, not a universal proof
that every hidden timer and activation domain is represented. Retain native
adversarial lifecycle controls and broader true-world survival checks alongside
gameplay coverage. Extend repeated seeds, archetypes and external public prior
coverage after resolving the failures this matrix identifies.
