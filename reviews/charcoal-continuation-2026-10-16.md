# Charcoal repair and controlled native continuations

The Charcoal-only repair enables **35 completed native search occurrences** in
the original 288-trajectory experiment. It does not, by itself, admit the
speed-control or spread/trade continuations. A separately frozen public-prior
coverage control enables the primary speed case: native search replaces
Wood Hammer with Protect and prevents **all eight sampled immediate terminal
losses**, under the same recorded opposing replies. No eventual win is established.

These are separate controls. The additional primary-case result cannot be
attributed to the Charcoal repair alone. No strategic weight, root command,
opposing root reply, RNG label, horizon, 8/3 search limit or decision budget
changed. No full-game benchmark or production promotion was performed.

## Mechanical certificate

The only production change adds `charcoal` to `CURRENT_FACT_ITEMS`.
The pinned native item handler applies `chainModify([4915,4096])` to Fire move
base power; it has no timers, counters, consumption or persistent callback
state. Fling remains an unsupported move. Transfers/removals are not newly
authorized, and unknown items are still rejected for inactive/fainted holders.

Native controls validate Fire damage increases, non-Fire damage is unchanged,
and Charcoal remains held without consumption flags. Format-valid six-member
fixtures cover living and causally fainted owned holders, plus explicit
opposing Charcoal hypotheses. Tests certify owned request/player/field
equivalence, the public-origin observation contract, and authoritative legal
menu equality for admitted hypotheses. Native/public inventory contradictions,
false projections, extra legal commands, unsupported Choice items, Fling and
mixed unsupported priors remain negative controls. Opposing item hypotheses
are not presented as observed inventory.

The native checkout is `a5df8274e85b0889bf2a9b3422a08b39732374fc`;
`data/items.ts` SHA256 is
`716d0b62c0df4f34b6678feabb9499ae4ecd2cb1b4a6c464092cd88d1ef3de88`.
The certificate does not bypass the existing public history, capability,
positive-projection or inventory gates.

## Exact Charcoal-only rerun

The failed-admission run is preserved at `runs/paired-continuation/v1`.
The Charcoal-only run is `runs/paired-continuation/charcoal-v1`, with its own
frozen manifest. Source comparison shows only `persistent_support.py` changed
between those two decision-source snapshots. The original prior catalogue
is unchanged in this run.

| Native continuation measure | Failed control | Charcoal only |
| --- | ---: | ---: |
| Trajectories | 144 | 144 |
| Completed search occurrences | 0 | 35 |
| Unique completed search computations | 0 | 30 |
| Changed action occurrences | 0 | 19 |
| Native fallback occurrences | 215 | 174 |

Each run also contains 144 frozen-V2 trajectories. Search/decision occurrence
counts can change when paths change. Cached occurrences are not independent
computations. All 35 Charcoal-only searches occur in the alternative-attacker
case, across 29 trajectories; no admission failure is counted as a search.

That case's alternative root has 3/24 sampled native-continuation wins versus
2/24 V2 wins, with zero terminal losses in either arm. Five native trajectories
have an unmatched later opposition schedule and remain explicitly separated.
On the **19 strictly matched** alternative-root trajectories the result is
still **3 versus 2 wins**. The added win is a matched scenario where native
chooses `Expanding Force into Venusaur + Steel Roller into Excadrill` instead
of V2's `Expanding Force + Psychic Fangs`, both into Venusaur. This is one
conditional terminal conversion witness, not a win-rate estimate.

## Why the priority cases remained blocked

The speed root publicly reveals Garchomp's Earthquake; the spread/trade root
reveals Metagross's Earthquake. The frozen priors have Stomping Tantrum in those
sets instead, so they contain no compatible candidate. Rejecting those models
is correct. Allowing Charcoal should not override conflicting public moves.

The second run, `runs/paired-continuation/earthquake-v2`, is therefore a
**separate public-prior coverage control**, not the Charcoal-only experiment.
Its explicit optional harness profile adds one legal Earthquake variant for
each of those two species while retaining every original set. All other set
fields and species priors remain unchanged. Public move revelation, not the
actual hidden team, excludes an incompatible original. If Stomping Tantrum is
still possible for an active opponent, the existing unsupported-capability
rejection remains in force. A dedicated test verifies this distinction.

This changes the experimental prior catalogue and is recorded in the manifest
with a profile name and hash. It does not change the production catalogue or
weaken admission. The additional candidate sets, rather than a weight change
or an expanded search, explain why the speed follow-ups become available.

## Priority speed case: requested four cells

Each cell is **terminal wins / losses out of 24 scenarios** at the original
short continuation horizon, in the separately labelled coverage control.

| Fixed root action | Frozen V2 follow-up | Public native follow-up, with fallbacks recorded |
| --- | ---: | ---: |
| Wood Hammer + Psychic Fangs | 0 / 8 | 0 / 0 |
| Protect + Steel Roller | 0 / 0 | 0 / 0 |

Actual search runs on **18/24** original-root trajectories and **20/24**
alternative-root trajectories. Every one of the eight avoided losses contains
a completed native search that changes V2's move. All **24 original-root
native paths strictly match the V2 opposing reply schedules**, so the loss
avoidance is not explained by weaker tested opposition. Seven alternative-root
paths cannot replay the full reference opposition schedule; on the **17 common
strictly matched root scenarios**, neither native root has a terminal win/loss.

Against the controlling root reply, all four RNG labels reach the forensic
position and choose **Protect instead of Wood Hammer** under successful public
admission. For label zero, there are two admitted public hypotheses:

| Candidate continuation | Sampled worst utility |
| --- | ---: |
| Protect | -2148.52 |
| High Horsepower into Excadrill | -2165.74 |
| Grassy Glide into Excadrill | -2177.68 |
| Wood Hammer into Garchomp | -1000000 |

The exact terminal-loss value distinguishes Wood Hammer from nonterminal
alternatives. No sacrifice ban or Protect bonus was needed. The same supplied
actual opposing reply and coupled labels then confirm survival after Protect.
This demonstrates prevention of a sampled terminal loss, **not** a winning
route. Protect may only delay an eventual loss.

The earlier eight-loss contrast therefore cannot establish that the initial
Rotom KO was a bad decision: its V2 continuation was a confound. With a working
native follow-up, the attacking root also survives the tested horizon. The
root's existing material preference is neither corrected nor certified optimal.

## Remaining cases and gates

Across the separate coverage-control experiment there are **73 completed search
occurrences**, **50 unique search computations**, **57 changed actions**, and
**136 fallbacks**. Admission and completion counts are both 73 here. Maximum
observed unique decision time is **1.181 seconds**, below the shared eight-second
budget. Forced waits are reported separately. None of these counts is pooled
with the Charcoal-only run.

Spread/trade remains **unanswered** by native follow-up: after its prior becomes
compatible, all 74 native-requested occurrences reject the public weather plan.
Its 9/24 versus 13/24 continuation wins remain frozen-V2 results. The
alternative-attacker case has the same native evidence as the Charcoal-only
run. Other fallbacks include supported-domain protection/residual exclusions,
public Trace state, turn-one replacement phases, and still-possible active
Stomping Tantrum. These rules were not relaxed to manufacture coverage.

The audit verifies unchanged frozen roots, six root replies, four RNG labels,
case identities and all **144 V2 action/opposition trajectories** in each run.
It checks factorial coverage, public information-set determinism, completed
search admission, changed actions, terminal facts, strict opponent replay,
and exact fallback parity. Targeted mechanical tests and the separate prior
profile test pass (**70 tests**); Ruff passes. Raw state/search traces remain ignored locally;
the tracked comparison contains compact evidence and archive hashes.

The next unresolved target is the spread/trade public-weather rejection, if
continuing this exact diagnostic. There is now direct evidence that admitted
native search can avoid V2's terminal mistake in the priority speed case;
there is still no basis here for new strategic weights or a general preference
for either root action.

Reproduce with the project virtualenv and `PYTHONPATH=src;scripts`. Historical
Charcoal-only manifests use the harness source at `aff7b8a`; the current
optional prior profile is separately frozen. Each manifest requires its exact
source hashes and a new output directory. `charcoal_continuation_comparison.py`
audits the preserved three-run sequence without rewriting any control.
