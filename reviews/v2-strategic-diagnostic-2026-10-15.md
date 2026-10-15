# Public match-plan diagnostic — 2026-10-15

Implemented the diagnostic milestone without changing action selection, search coverage/depth, the tactical scorer, or default V2. This produces inspectable working plans and unresolved tactical questions. It has not demonstrated better play or reliably diagnosed an action as a mistake.

## What was reused and added

The repository already contains `StrategicPlan`, desired-board requirements, resource purposes, position assessment, plan generation, and trade assessment. Reused those structures rather than adding a second strategy framework. The diagnostic adds an explicit provisional finisher, requirements, typing blockers, role providers, possible opponent objectives, a current investigative objective, and reassessment through observed turns.

The initial finisher rule is deliberately visible: retain a living prior damage anchor; otherwise prefer spread coverage, damaging move count, HP, then species name for deterministic ties. This is a hypothesis generator, not a competitive win-condition selector. Retention survives Mega Evolution. A fainted or unselected anchor triggers replanning; retained low-HP anchors are not automatically judged worth saving. Team selection itself is not implemented.

Opponent plans are bounded hypotheses: preview Tyranitar/Excadrill or Pelipper/Basculegion weather pairings, revealed Trick Room/Tailwind, and active opposing Tailwind. Preview possibilities are distinguished from active entrants. Unrevealed abilities, items, roster selection and speed remain unresolved. Unsupported teams explicitly receive an unknown opponent-plan result. This is not general opponent strategy recognition.

## Retained positions

Ran 24 opening cases and 12 existing turn-two checkpoints, including familiar and unfamiliar-set cases. For each opening, a roster-only preview is reconstructed from the known own six and public opponent preview; it contains no lead, opening weather, or observed opponent-set facts. These are **not retained live team-preview requests**. The next assessment sees only the recorded public opening. Midgame assessments replay each preceding own public decision view and update the prior plan.

The planner receives no winner, actual opponent command, native snapshot, search ranking or leaf utility. Own unrevealed roster information is legitimate input. Archive/source hashes, catalog fingerprint, full plans and report excerpts are retained. The full local artifact is `runs/v2-strategic-diagnostic/v1/plans.json`; the tracked companion JSON contains 36 excerpts.

Example: development psychic/sand opening

- Working finish: create repeatable or decisive attacks for Gardevoir.
- Observed: Gardevoir alive, Psychic Terrain present; these do not certify safe execution, grounding or remaining duration.
- Active blockers: Tyranitar is immune to Psychic by base typing; Excadrill resists Psychic and Fairy. Incineroar is a preview possibility rather than a confirmed reserve.
- Possible answers: Mega/Pixilate Hyper Voice against Tyranitar; Mystical Fire or Metagross Earthquake against Excadrill. These are typing checks, not KO, move-availability, accuracy, ability, or survival certificates. Mega conversion is conditional and the shared Mega resource still needs tactical checking.
- Available support: Indeedee supplies redirection, Trick Room, Imprison and terrain access. Availability is not evidence that using a tool now helps.
- Opponent hypothesis: enable Excadrill with sand. Weather is observed; Sand Rush and exact effective speed are not assumed.
- Current investigation: test an immediate finish/trade, removal or bypass of the active answers, and then a safe attacking window with a named next-turn payoff.

## Does it explain the known failures?

| Retained concern | Diagnostic contribution | Still unresolved |
| --- | --- | --- |
| Psychic chosen over Trick Room in development psychic/sand | Names the finisher, speed-order requirement, active answers, and setup provider together. | Cannot certify whether Trick Room changes the relevant attack order or survives the reply. Does not label Psychic incorrect. |
| Protect versus valuable attack/KO or trade | Requires a named next-turn payoff and comparison with attacking, partner intervention and trading. Does not declare support expendable. | No attack/Protect ranking, trade payoff, or survival proof is computed. |
| Validation psychic/sand: switch + Psychic wins some full games while Protect + Trick Room looks better in short diagnostics | Lists remaining damage and answer removal/bypass as alternatives to setup and preservation. | Neither the working anchor nor these explanations resolve the disagreement. The previous short-continuation result remains a counterexample to simplistic plan claims. |
| More candidates worsen outcomes | Plans provide requirements that could later explain why a high-utility branch is undesirable. | No evidence that these requirements repair the objective or select better candidates. |

The useful advance is a falsifiable vocabulary for the missing dependencies. The milestone does **not** pass a stronger claim that explanations reliably identify bad decisions. Existing plan generation also exposes old assumptions, such as unique-role preservation and generic speed-control goals; they are retained as unranked comparison candidates, not endorsed strategy.

## Boundary and next experiment

Psychic Terrain protects grounded allies from opposing priority. Trick Room's presence does not imply favorable order. A resisted attack does not imply the opponent must be removed. Redirection, switching, disruption, and support sacrifices require native tactical validation. No arbitrary support-loss approval or Protect/Trick Room bonus is emitted.

Next, take the sealed development psychic/sand plan and compare a small fixed set of already retained attack, setup, switch and defense lines. Record whether each line actually creates a usable attacking window, removes/bypasses an answer, or merely delays defeat, against the same responses and plausible worlds. Keep 8/3 and the current evaluator as controls; define these plan-outcome labels before consulting outcomes, and test their ranking on separate positions before coupling them to action selection. The public admission blockers still constrain any live midgame use.

Validation: 27 targeted strategic/diagnostic tests passed and Ruff passed. Tests cover public-information rejection, no input mutation, conditional counterplans, type conversion/immunity, Mega continuity, anchor loss, terrain loss, and absence of action selection. These checks establish diagnostic correctness, not strategic quality.

Reproduce using `PYTHONPATH=src`:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/strategic_diagnostic_review.py
../champions-practice-bot/.venv/Scripts/python.exe -m pytest tests/test_strategic_diagnostic.py tests/test_strategy.py tests/test_strategy_tactics.py -q
```
