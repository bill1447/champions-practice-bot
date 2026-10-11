# Protection and own Mega recovery — 2026-10-10

Implemented public protection-chain reconstruction and repaired the observed own Mega/ability materialization failures. This is a recovery milestone, not a declaration of universal mechanic support or production readiness.

## Implementation

Ordered public lifecycle evidence now records executed moves, prevention, switches and drags. Complete observed turns determine successful protection chains, failures, interruptions and switch resets. Incomplete or ambiguous histories remain unsupported. The native worker creates the corresponding stall volatile through pinned native lifecycle operations, including native restart counters and residual duration handling; it does not copy private oracle counters into production reconstruction.

Own Mega reconstruction now validates eligibility through the pinned native Mega operation, restores observed reserve ordering through native switches, completes final switch lifecycle initialization and compares request objects canonically. Native staging avoids disturbing Unburden actors. Exact own request, state and legal-action checks remain required.

## Final validation

1499 pytest tests passed. Ruff, worker syntax and diff checks passed. Native protection, own Mega, terrain lifecycle, present mechanics, execution evidence, execution authority and sealed transition controls passed. The human Mega regression completed with six searches, one protection-history fallback and one forced wait across eight decisions.

Final source-bound league runs used eight games per fixture with the existing seed and eight-second decision budget:

| Fixture | PR 236 | Terrain-only recovery | This change |
| --- | ---: | ---: | ---: |
| Current roster mirror | 5/51 (9.8%) | 6/51 (11.8%) | 7/54 (13.0%) |
| Synthetic spread uncertainty | 13/92 (14.1%) | 25/72 (34.7%) | 10/67 (14.9%) |

Final reports: `runs/strength-league/fbfc12c5710b21d0ce3c/report.json` and `runs/strength-league/a3292ff95537e6ae3f28/report.json`. Mirror searched 33 decisions and 38,535 branches; synthetic searched 45 decisions and 55,232 branches. Different trajectories and wall-clock search budgets mean these small runs establish regression evidence, not a precise causal estimate or superiority over PR 236.

No explicit unsupported protection-chain or exact own ability failure occurred in either final run. Remaining mirror fallbacks: four unsupported public protection histories and three unsupported terrain sources. Remaining synthetic fallbacks: six unsupported public protection histories, three unsupported terrain sources and one own team active-flag mismatch. The last mismatch is unresolved and must not be counted as recovered own-state support.

## Terrain review and next work

See [terrain assumptions review](terrain-assumptions-review-2026-10-10.md). Source identity is resolved at the public activation event rather than inferred from the final occupant of its slot. Repeated equal events are retained, and contradictory field histories are rejected. Native controls establish that switching a Surge user back into the same terrain does not refresh it; an intervening terrain overwrite does permit reactivation with a fresh duration. Retained Terrain Extender controls also pass.

Terrain remains qualified: copied/borrowed source abilities and uncertain Extender histories are unsupported. The review was conducted during implementation, not by an independently staffed reviewer. Do not declare terrain fully supported.

Next priorities are reproducing the remaining own active-flag mismatch, explaining missing/ambiguous public protection histories without weakening completeness checks, and recovering borrowed terrain-source abilities with public evidence and native operations. No deployment, commit or push was performed for this change.
