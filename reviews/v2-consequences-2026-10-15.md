# Native consequence-based tactical prototype

**Built and tested; experimental, not promoted.** Public V2 and PR #249 remain
unchanged at `e0ae723`. This work is isolated on `experiment/v2-consequences`,
based on the independent evaluation branch. The rejected shield experiment stays
on `experiment/v2-survival` and is not incorporated here.

## Audit and implementation

The repository already had exact native turn search, a named position scorer,
candidate diversification, and a selective continuation probe. The old probe
extends only one principal worst world/response/RNG branch for each shortlisted
root choice. The V2 default does not use it. The approximate V2 joint model is
also separate from that native infrastructure.

The prototype reuses Showdown's hypothetical-only worker, `ExactBeliefWorldState`,
and `score_exact_summary_breakdown`. It adds no learned model, live snapshots,
new hidden-state reconstruction framework, or move-scoring bonus.

* Public move ranking proposes a bounded native-legal menu, reserving attacking,
  per-slot Protect, speed control, disruption/redirection, switching, and
  complementary joint plans such as Trick Room + Protect. It does not make the
  final selection. Not every legal action or target variant is retained.
* Native branches resolve all four actors, with actual speed/priority, damage,
  abilities/items, Mega changes, Protect chains, disruption, switching, weather,
  terrain, recoil and forced replacements **within the supplied hypotheses**.
* Every sampled first-turn response/outcome is extended through the horizon.
  Replacement and pivot requests do not count as completed turns.
* Indistinguishable public observations with the same own command history share
  one continuation. The bot cannot choose a different counterplay just because
  the search internally knows which hidden-set hypothesis it is examining.
* Each response is averaged over the supplied hypothetical RNG samples; opponent
  alternatives are minimized, not assigned invented probabilities. Root choices
  maximize worst-world utility, with weighted utility as a tie-breaker.
* The reused position scorer values terminal results, material, HP, status,
  boosts, field resources and speed. It is still a hand-written utility with a
  large equal living-piece bonus, not a calibrated win probability or a complete
  understanding of remaining win conditions.

The trial bound is eight root actions, three opponent responses, two continuation
actions, two explicit worlds, one RNG sample per branch, at most six decision
phases and 4,096 native transitions. The total opening deadline is eight seconds,
including hypothesis construction/conditioning. An incomplete comparison retains
the authoritative legal V2 incumbent. Native mechanics are exact; **coverage and
the value assigned to the resulting position are not**.

## Evaluation boundary

These are **opening interventions**, not a replacement full-game bot. Both
variants use frozen V2 for every later action. This avoids pretending that the
prototype has solved ongoing public-state admission and belief maintenance.
Its evaluator can accept admitted midgame worlds, but that integration and its
gameplay coverage have not been tested here.

Opening hypotheses come from an explicitly limited static prior family. They
vary held item and selected bench; the actual hidden team is drawn from that
same family. The decision helper receives its own team, sanitized observation,
authoritative menu and public prior text. Actual enemy selection/item, command,
live snapshot and battle seed stay in the live driver. Hypothetical RNG is fixed
independently. Observed owned genders and Trace ability condition hypotheses.
This is a closed-family mechanics experiment, not a broad hidden-set benchmark.

Three development matchups and three separate-composition matchups were frozen
before play, with two live seeds/hidden variants and both side assignments.
Species/set families and some compositions appeared in earlier project research;
the separate-composition stage is not a pristine project-wide held-out test.
The independent opponent is still the installed simple heuristic, which normally
does not Mega evolve. Mirrored and shared-team outcomes are correlated.

## Results and depth ablation

Final primary comparison: **72 complete games**, 24 matched three-way cases.
One-turn and two-turn controls share hypotheses, root proposals, response limits,
native mechanics and the position scorer; only their horizon differs.

| Suite | Frozen V2 | Native one turn | Native two turns |
| --- | ---: | ---: | ---: |
| Development | 2/12 | 2/12 | 2/12 |
| Separate compositions | 3/12 | 8/12 | 8/12 |
| Combined | 5/24 | 10/24 | 10/24 |

Two turns has five candidate-only wins and zero V2-only wins. One turn has six
candidate-only wins and one V2-only win. Comparing the native horizons directly,
each wins two games that the other loses. These are small, correlated results,
not evidence that the full bot has doubled its general win rate.

The native evaluator improves some openings. **The extra turn has not earned a
general strength claim:** it costs about 5.02 seconds per opening (maximum 6.98),
versus 0.35 seconds (maximum 0.60) for one turn, with the same aggregate wins.
There are no final search failures, deadline overruns or opponent random legal
fallbacks in the primary comparison. Both horizons completed all 24 searches.
Twenty two-turn openings differ from V2; development changes still do not alter
any game winner. The difficult original psychic/sand and ground/rain cases remain
losses. This remains far from a competent full-game opponent.

The recorded independent opponent response occurs in the three-response
shortlist in **12/24** cases under every hypothesis, for both horizons. Missing
half the actual replies is a concrete coverage problem. Native exactness and
another ply cannot compensate for a missing relevant response.

## Native diagnostic witnesses

After all recommendations were sealed, five saved opening positions were restored
and each plan tested against the recorded enemy reply with eight coupled future
RNG samples. The actual snapshot was used only by this diagnostic, never by the
decision helper. These are first-decision conditional witnesses, not optimality
or win-probability estimates.

* Original Gardevoir/sand opening: both native horizons switch Gardevoir to
  Metagross while Indeedee attacks. Four own Pokémon survive in all eight samples,
  versus three for V2's Psychic + Mystical Fire Mega. The full game is still lost.
* Armarouge/Indeedee versus Incineroar/Rillaboom: one turn chooses Protect + Trick
  Room; two turns chooses Armor Cannon + Trick Room. In all eight samples the
  attacking plan KOs a foe while preserving all four own Pokémon. Protect gives
  up that KO. This demonstrates a concrete alternative to automatic preservation,
  although neither opening changes this full-game result.
* Ground/grass versus rain: one turn protects Garchomp; two turns switches it to
  Dragonite. Both preserve four own survivors in every sample and win the saved
  full game. V2's attack line loses a Pokémon in every sample.
* In the psychic/sand validation witness, Protect + Trick Room and switching
  both preserve four Pokémon immediately. The two-turn switch line wins the
  recorded full game while the one-turn shield line loses. Immediate survival
  alone does not distinguish them.
* In the Armarouge validation witness, two turns chooses Follow Me + Armor Cannon
  and obtains a KO in all eight samples, sometimes sacrificing a partner. The
  one-turn Trick Room + Protect line preserves all four but gets no immediate KO.
  Here the one-turn line wins the recorded full game and the two-turn line loses.
  Even a seemingly favorable short trade is not sufficient position valuation.

## Coverage repairs and verification

The initial `v1` run is retained separately at source commit `4508130`. Four
recommendations hit a four-phase cap because a pivot and subsequent residual
replacement can require another native decision before the second turn ends.
Two failed opening admission because four independent Trace proposal seeds did
not reproduce the observed owned ability. The `v2` source at `d4e65b6` increases
the bounded phase cap to six and conditioning proposals to sixteen. It does not
retune scoring or memorize a winning move. The final run replays the same cases;
the first 48 games are **not pooled as independent evidence**.

An exposed adapter bug parsed `trickroom` as upstream `Field.UNKNOWN`. The mapping
now uses the actual upstream enum IDs. The unchanged upstream heuristic does not
use that field, and replaying **349** decisions from all 48 final two-way games
proves that the mapping repair changes no recorded enemy action or result. The
one-turn control uses the repaired adapter. Package/adapter and all run source
hashes are retained in manifests and the report.

Nine focused tactical tests cover sacrifice versus preservation across horizons,
shared decisions across indistinguishable worlds, forced replacement/pivot turn
accounting, budget retention, public admission, authoritative menus and RNG
continuation coverage. An additional adapter test covers Trick Room mapping.
**1,692 tests pass**; lint and whitespace checks pass. The audit validates archive
provenance, matched seeds/teams/sides, unchanged later actions and replays **522**
frozen baseline rankings. Native witnesses and compact summaries are in the JSON
companion. Raw runs remain ignored under `runs/v2-consequences`.

## Next decision

Do not enable this globally or expand depth yet. The useful next experiment is
better response/candidate coverage at one turn, using these traces to identify
missing realistic actions and then testing against fresh cases. Any continuation
should demonstrate additional gameplay benefit against that cheaper native
control. Full-game integration must separately show that admitted midgame worlds
remain available and that gains survive beyond a single opening intervention.

Reproduce with `PYTHONPATH=src` and the sibling virtual environment:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/tactical_consequences_evaluation.py --seeds 2 --output runs/v2-consequences/v2
../champions-practice-bot/.venv/Scripts/python.exe scripts/tactical_consequences_ablation.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/tactical_consequences_report.py
```

The provenance audit also requires the retained initial `v1` archive. No commits
from this experiment have been pushed.
