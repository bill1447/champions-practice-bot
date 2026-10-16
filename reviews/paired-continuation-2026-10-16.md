# Paired continuation experiment: admission blocks the native comparison

The requested **two root actions x two continuation policies** ran on all three
retained positions, with **288 trajectories**. The public native arm completed
**zero searches**: all 215 actionable decision occurrences fell back to frozen
V2. Consequently, this experiment does **not** identify native continuation
quality or establish that native search repairs any of the three decisions.

A separate exact-state forensic does identify a concrete V2 follow-up loss mechanism
in the primary speed-control case. It is explicitly not counted as public
admission, native policy success, a winning route, or a full-game improvement.
Strategic weights, admission, native search and production behavior are unchanged.

## Controlled comparison

The frozen manifest fixes both root commands, original exact hypotheses,
original six root replies per position and four coupled RNG labels. Roots were
regenerated and checked against their archived public observation. Initial
opposing replies are identical across all four cells. Subsequent V2 opposing
reply schedules are replayed at matching turn/phase/occurrence whenever legal;
unmatched schedules would be reported separately. In this run, **all 144 native
trajectories strictly matched their V2 reference opposition schedules**.

Both follow-up policies receive only their own public observations, including
the public six-mon preview, owned requests and history. The driver holds exact
states for branching; no exact state or actual enemy team is supplied to the
native player. It uses the existing frozen public prior catalog, public ledger,
admission gate and shared eight-second preparation/search budget. Each new
decision is bounded through the existing player implementation.

The earlier exact-world benchmark's default views exposed the selected four.
The corrected six-mon public preview is supplied to both continuation arms
here. All **144 V2 trajectories reproduce the earlier first/second-turn
outcome facts and utilities** despite that correction. This is outcome parity,
not a claim that every intermediate action was independently archived before.

Memoization uses the full public observation/action history, including public
event deltas, legal menu and known own team. It contains no world, opposing
command, RNG-label or hidden-state keys. Unique computations and decision
occurrences are reported separately; repeated cached fallbacks are not new
admission attempts or search successes.

## The four cells

Each entry is **terminal wins / terminal losses out of 24 scenarios**, after
one additional completed turn. These are conditional samples, not probabilities.

| Position / fixed root | Frozen V2 follow-up | Native requested, all fallback |
| --- | ---: | ---: |
| Speed: Wood Hammer + Psychic Fangs | 0 / 8 | 0 / 8 |
| Speed: Protect + Steel Roller | 0 / 0 | 0 / 0 |
| Spread/trade: Earthquake + Protect | 9 / 0 | 9 / 0 |
| Spread/trade: Earthquake + Expanding Force | 13 / 0 | 13 / 0 |
| Alternative attackers: Mystical Fire + Protect | 0 / 0 | 0 / 0 |
| Alternative attackers: Hyper Voice + Steel Roller | 2 / 0 | 2 / 0 |

All fallback-only paths match their V2 control actions, opposing replies and
first/second-turn measurements exactly. The matching columns are a fallback
integrity result, not evidence that native and V2 decisions are equally good.
Nonterminal survivors can still lose later.

## Admission telemetry

| Reason | Actionable occurrences | Unique computations |
| --- | ---: | ---: |
| Unsupported Charcoal | 112 | 82 |
| Unsupported opponent capabilities | 74 | 48 |
| Unsupported switch phase at turn 1 | 27 | 25 |
| Unsupported public trace state | 2 | 2 |
| **Total fallbacks** | **215** | **157** |

There are also **160 forced-wait occurrences**, reported as nonactionable.
No decision admitted a native world, so no failed admission is counted as
successful continuation. Charcoal was introduced during fresh-benchmark team
validation to satisfy Item Clause; the exact simulator handles it, but the
deployed public admission contract rejects it, even when it belongs to a
previously fainted owned member. The exact-world benchmark bypassed this gate.
No item was changed or gate weakened after observing these results.

## Which response controls the root score?

| Position | Selected root's controlling reply | Alternative's controlling reply |
| --- | --- | --- |
| Speed | Garchomp Protect + Rotom Thunderbolt into Metagross | Same |
| Spread/trade | Metagross Psychic Fangs into Garchomp + Venusaur Protect | Same |
| Alternative attackers | Excadrill Protect + Rillaboom High Horsepower into Metagross | Excadrill High Horsepower + Rillaboom High Horsepower, both into Metagross |

All these replies are legal within the original supplied hypotheses. Their
real-world likelihood is unmeasured; being damaging does not make them
implausible. We do not assign response probabilities.

For the speed case, selected/alternative worst utilities are **-2147.73 /
-3242.86**. Equal-reply means are **-1507.78 / -2233.70**. The selected root is
also preferred by a simple reply mean. The other two retained pairs likewise
retain their ordering under the equal-reply mean. Thus a switch from minimum
to simple mean does not resolve these particular pairwise rankings. This is a
diagnostic sensitivity check, not a calibrated risk policy or a general
exoneration of worst-case search.

The speed floor is especially revealing. Both roots leave **one living own
Pokemon, Rillaboom**. The attacking root removes Rotom; the protective root
leaves four enemies rather than three. Of the **1095.13** utility difference,
**1000** comes from that extra enemy KO, with HP and positional terms accounting
for the rest. This is not an extra saved own Pokemon being overvalued.
Removing Rotom also allows Excadrill to enter, changing the next-turn threat.

## Primary-case forensic: what V2 actually does

This exploratory diagnostic uses the same controlling root reply and all four
original RNG labels. It enumerates all ten legal next-turn commands for each
root against the same frozen-V2 opposing reply: **8 states, 80 branches**.
Some native legal commands target a fainted ally; those are retained for audit,
not offered as sensible tactical alternatives.

After the attacking root, Rillaboom starts the next actionable turn at
**177/207 HP**, facing Garchomp and the newly entered Excadrill. V2 chooses
**Wood Hammer into Garchomp**. Garchomp uses Dragon Claw and Excadrill Iron Head:

- In two labels, Rillaboom is knocked out before attacking.
- In two labels, Rillaboom KOs Garchomp, then faints to Rough Skin plus recoil,
  immediately losing because it is the final own Pokemon.
- Protect survives that fixed turn in all four labels. Grassy Glide into
  Excadrill survives two labels while dealing damage; it still loses in two.

After the protective root, Rotom is still present, Rillaboom starts at
**207/207 HP**, and V2's Wood Hammer into Rotom survives all four labels.

This demonstrates that frozen V2 selects a terminally losing line when a legal
nonterminal line exists against the same supplied response. Merely delaying
a loss would not establish a better strategic decision. It does **not** prove
that Protect leads to a win, that the
attacking root is strategically sound, or that a public native policy would
choose the forensic alternative. The benchmark therefore cannot yet attribute
the eight-loss difference exclusively to the root evaluator. The threat
created by an immediate KO and the continuation's contact/recoil choice both
deserve explicit attention before changing a material coefficient.

## Validation and next step

The audit checks source/manifest hashes, all 288 factorial cells, complete
reply/RNG pairing, deterministic choices for identical full public histories,
fallback legality, exact fallback/control trajectory parity, and terminal
utilities. The forensic checks eight original-label cells and 80 distinct
legal command branches. Ruff and syntax checks passed. No production source
or tests changed; this is diagnostic work only.

The next experiment needs genuinely admitted continuation decisions on these
same roots. Until the bounded admission blockers are resolved in a separately
validated mechanical change, the native-versus-V2 causal question remains
blocked. Preserve this failed-admission run as the control; do not relabel an
exact-state forensic as native player success or quietly substitute new items.

Tracked files are the paired manifest, paired results (including compact
forensic facts) and this report. Raw traces and the expanded forensic report
stay ignored under `runs/paired-continuation/v1` and
`runs/paired-continuation/speed-forensic-v1`.

With the project virtualenv and `PYTHONPATH=src;scripts`:

```text
python scripts/paired_native_continuation.py evaluate --output runs/paired-continuation/NEW-RUN
python scripts/speed_continuation_forensic.py --output runs/paired-continuation/NEW-FORENSIC --report runs/paired-continuation/NEW-FORENSIC/forensic-report.json
python scripts/paired_continuation_report.py --archive runs/paired-continuation/NEW-RUN/results.json.gz --manifest reviews/paired-continuation-manifest-2026-10-16.json --forensic runs/paired-continuation/NEW-FORENSIC/forensic-report.json --output reviews/NEW-REPORT.json
```
