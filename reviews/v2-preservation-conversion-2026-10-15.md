# Preservation versus conversion diagnostic — 2026-10-15

The diagnostic finds **one concrete selection weakness**, **one material-value/continuation mismatch**, and **two cases where Protect creates a genuine opportunity**. A general Protect penalty would address the wrong problem.

Admission expansion is frozen. No production source, strategic weight, leaf evaluator, prior, search limit or eight-second decision budget changed. Existing full-game results remain 15/24 versus 10/24; this experiment provides no additional strength evidence.

## Frozen experiment

Four retained public checkpoints from the inventory full-game archive were selected before running:

1. Newly admitted Venusaur Protect, development Armarouge support / grass balance, shifted family, turn 5.
2. Newly admitted 2.1%-HP Armarouge Protect, validation Armarouge pivot / grass water, shifted family, turn 5.
3. Earlier repeated-Protect loss, the same validation composition against MaxBasePower, turn 2.
4. Earlier lone-Venusaur Protect in psychic / sand, turn 5.

Roots are freshly admitted from the recorded public lifecycle, own team and unchanged approved priors. The experiment receives no actual hidden-state snapshot or truth RNG. It reproduces all four production one-turn 8/3 choices and scores, then compares a bounded set of attacks, the selected shield, and every legal switch of the focal actor while preserving its partner's command. It also retains V2 and the best covered focal attack as references. Switching is unavailable in the two Venusaur endgames; no switch is invented for them.

Each candidate faces identical per-world replies and **eight coupled initial RNG labels**: the production label plus seven fixed diagnostic labels. The original three replies are reported separately from the recorded opposing command. That recorded command is a forensic reference, never a deployed prediction. It is legal in every supplied world; only the repeated-Protect case has a recorded command outside the original three.

There are **704 root samples**: 624 across the three covered responses and 80 additional recorded-response samples. Hidden-HP alternatives and repeated seeds/responses are correlated; these are not independent games, opponent probabilities or confidence estimates.

The root action is followed through replacement/pivot pauses and one additional completed turn using frozen V2 for our choices and the existing independent opponent for theirs. Own choices are checked for equality across identical public information and own action history. There are no continuation opponent-adapter fallbacks.

Because V2 can miss an opportunity, a separate audit reruns the unchanged native one-turn 8/3 kernel at **41 grouped next-turn information sets** from the production RNG label. Indistinguishable leaves share one choice across hypotheses; there is no per-hidden-world oracle action. Selected native follow-up moves are executed against their modeled replies to retain move/status witnesses. These single-label witnesses establish possibility, not reliability. A native follow-up may use the carried hypothetical state even where a fresh public reconstruction would later be unsupported.

## 1. Repeated Protect loses an exact-score tie it should not lose

The default production matrix gives Follow Me + Protect and Follow Me + Armor Cannon the same **-1061.4** worst-world utility and the same weighted-worst utility. The attacking action is **no worse in every supplied world/response bin and strictly better in others**.

In one of the identical two-world response tables:

| Opposing response | Follow Me + Protect | Follow Me + Armor Cannon |
| --- | ---: | ---: |
| Wood Hammer + Hydro Pump | -1046.96 | 4.42 |
| Protect + Hydro Pump | -1061.40 | -1061.40 |
| Wood Hammer + Protect | -54.46 | 1047.60 |

The kernel discards non-worst response advantages, then breaks the remaining exact utility tie by the proposal's shortlist position. Follow Me + Protect entered earlier. This is a concrete **dominance-blind tie-selection weakness within the sampled matrix**, not evidence that Protect needs a move-specific penalty. The existing `weighted_utility` averages per-world worst values; it does not average opponent responses.

The eight-label sweep strengthens the counterexample within these scenarios: first-turn Armarouge survives **44/48** covered-response samples after Protect versus **48/48** after Follow Me + Armor Cannon. The attacking line's worst world/response RNG mean is -1061.40 versus Protect's -1326.94. No sampled line ends the game within the two-turn probe. The recorded Wood Hammer target differs from the covered response, but Follow Me makes those target variants converge to the same public follow-up position for the shield/matched-attack comparison; the literal missing command alone does not explain that comparison.

The bounded next selection fix to investigate is to avoid choosing a pointwise-dominated action among otherwise tied robust candidates before falling back to proposal order. It should have a general dominance regression and a nondominated Protect control, followed by independent paired gameplay. No such selection fix is deployed here.

## 2. Low-HP Armarouge demonstrates the preservation/conversion mismatch

At 2.1% HP, Armarouge contributes approximately **1000 living-material points plus 2.1 HP points** while alive, before position terms. The one-turn default favors Flare Blitz + Protect at **2055.70** worst utility. Its controlling leaf has +2000 net living points, +102.08 HP points, -43.69 position and -2.70 speed. This generic living-member value does not require a named future contribution from Armarouge.

The simulator does recognize sampled immediate wins from attacking and assigns the correct **+1,000,000 terminal score**. The problem is not a terminal-win detection failure: those wins are discarded by the per-response minimum when another response produces a nonterminal trade. Controlled re-ranking of the exact frozen matrix confirms:

- Removing only the living-material component changes the selection to an attacking line.
- Removing HP, position or speed alone does not change Protect.
- Mixing response means with their minimum changes the selection to offense; this is sensitivity evidence, not a calibrated risk policy.
- Averaging hidden worlds alone changes none of the four cases. This does not validate the narrow root priors.

The independent-continuation measurements make the future-value issue concrete:

| Root line | Terminal wins after first completed turn | Terminal wins after one further turn | Armarouge survives first / second |
| --- | ---: | ---: | ---: |
| Flare Blitz + Protect | 0/48 | 4/48 | 48/48 / 4/48 |
| Flare Blitz + Armor Cannon | 22/48 | 48/48 | 0/48 / 0/48 |
| Darkest Lariat + Armor Cannon | 20/48 | 48/48 | 0/48 / 0/48 |
| Flare Blitz + immediate Venusaur switch | 2/48 | 48/48 | 48/48 / 46/48 |

These counts are conditional on the fixed responses, admitted worlds, sampled RNG and frozen continuation, not win probabilities. After root Protect, Armarouge deals **no direct enemy damage** in the V2 continuation samples. Both immediate sacrifice and immediate repositioning reach the sampled finish much more consistently.

The native next-turn audit also reproduces the practical concern: after the modeled Darkest Lariat or Flare Blitz response, native search chooses **Flare Blitz + switch to Venusaur**, preserving Armarouge on the bench. That avoids treating the V2 continuation as the only plausible future, but still does not provide a necessary contribution from the saved Armarouge. The original full-game outcome was a win under both paths, with the preservation path taking two extra turns.

This is evidence to improve how conversion and viable resources are evaluated; it is not proof that sacrificing Armarouge is always correct. The immediate switch is a particularly useful alternative-route control because it preserves Armarouge while letting another attacker finish.

## 3. Venusaur's newly admitted Protect has an observable payoff

The corresponding development endgame does not support a blanket preservation criticism. Under the three covered replies, Protect retains Venusaur in **48/48** first-turn samples and Venusaur deals direct enemy damage on the following turn in **48/48**. V2's Energy Ball line retains Venusaur in 44/48 initially and produces four terminal losses by the second completed turn, compared with none after Protect.

A better covered attack, Sludge Bomb into the other target, produces 36/48 sampled terminal wins by the second turn versus Protect's 32/48, but also two losses versus zero. The eight-label response-mean utility reverses the default single-label ranking for this attack, illustrating RNG sensitivity and the distinction between sampled downside and conversion speed. It does not establish an opponent distribution or justify choosing a response-risk coefficient from these cases.

Native follow-up controls witness actual productive attacks and, against the appropriate revealed reply, Sleep Powder. Protect is buying an actionable next turn, not merely an extra living count.

## 4. The lone-Venusaur case exposes a continuation-policy confound

V2 loses in all 24 covered-response continuation samples after Protect, which initially looks like pure delay. However, Protect carries Venusaur through Trick Room's expiry. Its ordinary Speed then exceeds the remaining attackers'. The native next-turn audit selects **Sleep Powder into Incineroar** instead of V2's Energy Ball into Tyranitar.

Direct native execution witnesses show Sleep Powder landing and Venusaur surviving the following turn. This is not a proven winning route, and the witnesses use one coupled RNG label rather than an accuracy estimate. Nevertheless, it is a concrete opportunity that the V2 continuation misses. Calling this Protect intrinsically useless based only on that rollout policy would be incorrect.

This is also a way to prioritize a future missing capability: publicly reconstructing sleep may matter because a named, mechanically witnessed tactic creates it. That work remains frozen during this diagnostic; native continuation availability does not certify fresh public admission after sleep.

## What to change next

First test the general dominated-tie selection correction against separate decision cases. Keep the preservation cases where Protect enables a witnessed attack or speed-window transition as negative controls against overcorrection.

Then investigate conversion evaluation using the low-HP Armarouge case, explicitly comparing a sacrifice, immediate Venusaur entry and delayed Venusaur entry. Require a measured next opportunity or an already terminal result rather than treating every living member as equally useful. Keep response-risk and RNG sensitivity separate from any strategic evaluator change; do not tune them jointly on these four examples.

Broader opponents, including independently validated legal Mega behavior, remain necessary before new strength claims. Neither a lower Protect rate nor higher admission coverage is a success criterion for this work.

## Validation and artifacts

- Root choices, worst utilities and production-label immediate branch decompositions reproduce the recorded 8/3 controls.
- Every compared action faces the same per-world response set and eight RNG labels; no partial sample cells are accepted.
- Every measured terminal win/loss receives the existing exact positive/negative million-point value.
- Frozen own continuation actions agree for identical public information/history; native continuation controls group indistinguishable hypotheses.
- Frozen source hashes match. Both diagnostic/report scripts pass Ruff. Production source and its previously passing 1,746-test implementation remain unchanged; no gameplay suite was relabeled as fresh validation.

Frozen protocol/source hashes and full raw results: `runs/v2-preservation-conversion/frozen-v4/manifest.json` and `results.json.gz` (local archives, not tracked). The earlier v1 draft stopped on a diagnostic forced-wait indexing error; v2/v3 drafts and v1 partial results are excluded from final counts. The v4 snapshot handles wait menus and includes direct native follow-up execution witnesses.

Tracked source and condensed evidence: `scripts/preservation_conversion_diagnostic.py`, `scripts/preservation_conversion_report.py`, and `reviews/v2-preservation-conversion-2026-10-15.json`. In PowerShell, reproduce with `$env:PYTHONPATH='src;scripts'; python scripts/preservation_conversion_diagnostic.py --output runs/v2-preservation-conversion/new-run`, then `$env:PYTHONPATH='src'; python scripts/preservation_conversion_report.py --archive runs/v2-preservation-conversion/frozen-v4/results.json.gz --output reviews/v2-preservation-conversion-2026-10-15.json`.
