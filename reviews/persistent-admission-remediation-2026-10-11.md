# Response to the independent #237–#239 review (#240 gate)

The human-supplied review is the independent review artifact for #237–#239 and
stands in for the #240 gate. It found admitted wrong worlds for opponent Fake
Out, own sleep and own Flash Fire, plus owned Fake Out disabling midgame search.
Matching observations and menus did not establish latent native state. The
reported `review/adversarial-review-2026-10-11.md`, `latent_probe.py` and
`flashfire.py` were not present in this workspace; they were not executed or
silently reconstructed as though they were the original files. The controls
below are new local reproductions based on the supplied findings.

This response records implementation and validation. It does not claim an
independent re-review of the new implementation or universal mechanics support.
Validation was completed before the remediation commit and push. No deployment
or merge was performed for this response.

## Changes and acceptance evidence

| Finding | Remediation and evidence |
| --- | --- |
| P1 — admitted wrong persistent state | Closed event, volatile and static-capability contract; unknowns are unresolved. Check complete public history before construction, every public-compatible opponent catalog candidate before bounded sampling, and native counters before admission. Identical observations/menus cannot bypass an observed unsupported effect. |
| P1 — opponent Fake Out phantom threat | Native regression exposes the old projection check approving a world whose opponent Fake Out is available after a completed move, while the real menu disables it. The new validator rejects that candidate. Public move/cant counts and native reconstruction restore the real eligibility. |
| P1 — owned Fake Out disables recovery | The old materializer fails the owned menu on turn two; repaired materialization matches both menus and produces admitted particles in the bounded control. Both sides, switches out/back, a real fainted replacement and a mid-turn Parting Shot pivot are exercised. Pending pivots remain unresolved; complete native continuations are tested. |
| P1 — own sleep and Flash Fire | Actual native sleep histories expose a fresh-counter difference in the old constructor; actual Flash Fire activation exposes its missing boost. Both are rejected before any production fresh construction. No sealed counter is used to repair them. |
| P2 — projection-only/mocked safety tests | New pinned-native controls assert tenure, all brought members' PP, current mechanical observations and both menus, then matched next-turn damage, status, boosts and flinch outcomes under three fixed seeds. A positive first-entry Fake Out must actually flinch. Corrupted Protect counters and terrain timers fail the independent validator. Older mock tests explicitly test projection/transport only. |
| P3 — skipped lifecycle checks | Every lifecycle smoke is a separate CI step with `!cancelled()` and prerequisite-success guards. A failed earlier smoke neither hides later independent results nor clears the failing job status. |

The native constructor uses switchIn/endTurn and inert external move entries to
restore public field tenure and move-entry counts. Pinned Champions Fake Out
uses `activeMoveActions`, which increments before prevention in runMove; it is
not equivalent to calendar turns. Native deductPP restores ordinary visible
opponent move uses, including members that have switched out. Pressure,
PP-changing/called moves and unclassified capabilities remain excluded.

Independent native-candidate checks verify these counters, shared stall
counter/duration, supported field timer/source, current Trace copy provenance,
and the existing exact own request/state, public opponent constraints and legal
menu. Counter values come from public evidence and the hypothetical world;
the actual native battle is an offline oracle only.

## Explicit unresolved domains

Sleep/toxic counters, observed Flash Fire and other unrestored volatile
histories prevent fresh search. Isolated native callback controls produce and
reject Encore, Taunt, Imprison, Substitute, confusion, Salt Cure, Perish Song,
toxic and silent choice lock. These synthetic callback inventories are not a
team-import/learnset validation or proof that each produced an admitted historic
defect. The review's initially unexecuted suspicions remain distinct from its
verified defects.

Encore and Stomping Tantrum capabilities are rejected even without a current
volatile: future effects depend on lastMove/moveLastTurnResult, which the inert
tenure scaffolding does not reconstruct. Unburden on either side is unresolved;
cached owned Speed alone is not an activation/reset lifecycle proof. Opponent
inventory changes and damaged/statused reserves are also unresolved rather
than restored to a fresh inventory or full HP. The gate returns a legal fallback
and grants no negative exclusion authority.

Supported uncertainty is retained: a source whose item is publicly unrevealed
can have ordinary terrain or Terrain Extender. A full-production native control
admits both remaining-duration worlds, 4 and 7, from the same public checkpoint,
with zero exhaustive exclusions. Missing disclosure does not select absence.
The prior catalog remains bounded; this is not a proof that unrepresented sets
are impossible or that arbitrary imported teams are supported.

## Validation and source identity

- Parent commit: `02b2787cccda09b9edfb0124830fcfcad67bba2c`; validation covered the remediation working tree before commit.
- Pinned Showdown: `a5df8274e85b0889bf2a9b3422a08b39732374fc`.
- Runtime source SHA-256: `5d2315766a7dc77702dff0263db8340a1bf8ef05c54852a9ba4c6e0bf3b9bdd6`.
- Full pytest: **1,569 passed**. Ruff and diff whitespace checks pass.
- Persistent admission, present-mechanics, execution-authority and recovery
  soundness native controls pass. Soundness retains the true world in all five
  tested boundaries (four witnesses, one unresolved, no false exclusions).
- Protect, own Mega, terrain source/reactivation, replacement, Trace/Trick Room,
  diversity-boundary and public-ledger lifecycle controls pass. These validate
  their own domains, not global fresh-state eligibility.
- Human-Mega seed 7, preview `team 3124`, eight decisions: one opening search,
  one forced wait and six explicitly predicted safety fallbacks. The public
  Mega ledger remains intact; no ledger-unavailable fallback occurs.
- Frozen run re-audit: mirror `81f191550de3b072bdaf`, **26/26** saved midgame
  action checkpoints unresolved; synthetic `9b43c2591625e1bf3a67`, **44/44**
  unresolved. Reasons total 39 owned-Unburden, 27 opponent-inventory, four sleep.
  Trace counts from the original reports remain historical, not current
  admission measurements. Audit outputs are in `runs/admission-audit/`.

The earlier zero-fallback and win reports cannot establish mechanical
correctness or strength. Re-auditing old checkpoints is not a new game run and
does not predict an unchanged battle trajectory under fallback actions. No new
strength claim or benchmark win comparison is made here.

From the repo root, after building pinned Showdown:

```powershell
.\.venv\Scripts\python.exe -m champions_practice.persistent_admission_smoke
.\.venv\Scripts\python.exe -m champions_practice.human_mega_regression_smoke
.\.venv\Scripts\python.exe -m champions_practice.admission_audit runs/strength-league/81f191550de3b072bdaf/report.json runs/strength-league/9b43c2591625e1bf3a67/report.json
```

## Next acceptance gates

Recover Unburden activation/reset from public item and entry lifecycle evidence,
and opponent inventory consumption without restoring already-used items.
Demonstrate exact relevant next-turn effects across switches, pivots and
post-upkeep replacements, including multiple possible latent states when the
public channel is not decisive. Then restore damaged/statused reserves and
last-move/result histories. Weather/Tailwind and the remaining volatile domains
need the same evidence and native-outcome standard. Keep learned priors,
strength claims, arbitrary import and deployment on hold while those broader
correctness and coverage gates remain unmet.
