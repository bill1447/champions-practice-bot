# Strategic reasoning framework

This document records the strategic concepts that should guide Phase 9. It is a compact
implementation interpretation of VGCGuide material, not a copy of the source text.

## Source-derived principles

### Game plans are objectives, not clicks

Source: https://www.vgcguide.com/what-is-a-game-plan

A game plan describes how a team intends to win and what must be accomplished along the
way. The bot should therefore represent objectives, required resources, desired future
boards, failure conditions, and the expected pace of the battle separately from the
concrete move chosen this turn.

Implementation consequence: `WinCondition` and `DesiredBoard` describe the future we want;
exact Showdown search remains responsible for finding a legal tactical path toward it.

### Positioning is future-board management

Sources:
- https://www.vgcguide.com/switching
- https://www.vgcguide.com/protect-in-battle

Switching and Protect are valuable when they improve a later board, preserve a critical
piece, create a safer partner pairing, or consume turns of a temporary opposing advantage.
Their value is contextual rather than a fixed material score.

Implementation consequence: strategy must be able to value a low-HP but necessary resource,
a temporary sacrifice, and a move that improves the next board even when it deals no damage.

### Speed control is a timed strategic resource

Sources:
- https://www.vgcguide.com/speed-control
- https://www.vgcguide.com/battling-against-trick-room

Tailwind, Trick Room, and other speed-control effects change which side can apply pressure.
Because major field effects expire, the important question is not merely whether one is
active but whether the side benefiting from it can convert its remaining turns into a win.

Implementation consequence: strategic state should track active speed-control effects,
available speed-control tools, effective turns, and whether the desired endgame can be
reached before the window expires.

### Preserve resources by function, not by fixed species value

Sources:
- https://www.vgcguide.com/switching
- https://www.vgcguide.com/protect-in-battle
- https://www.vgcguide.com/1-hp-is-infinitely-more-than-0-hp

A Pokemon can remain strategically important at very low HP if it is still the only answer
to a threat, the only speed-control setter, a required redirector, or the intended cleanup
piece. Conversely, a healthy Pokemon may be expendable once its strategic job is complete.

Implementation consequence: `ResourceAssessment` identifies roles and unique living role
providers. Plan generation then decides which resources are required, preserved, or
acceptable to lose for the current objective.

### Robust plans beat unnecessary hard reads

Source: https://www.vgcguide.com/predictions

A strong line should account for the opponent's plausible options rather than depending on
a single guessed move whenever a safer line exists. More committed predictions become more
reasonable when no robust line covers the position.

Implementation consequence: plans are evaluated across posterior belief mass and later
adversarial tactical replies. The strategy layer reasons about coverage and failure
conditions instead of treating the most likely hidden world as truth.

### Team modes matter

Sources:
- https://www.vgcguide.com/cores-and-modes
- https://www.vgcguide.com/team-preview

A team can have multiple practical modes with different leads, back Pokemon, speed plans,
and endgames. Team preview should select a four-Pokemon configuration that can answer the
opponent's likely threats while still advancing a coherent mode.

Implementation consequence: later Phase 9 work should explicitly represent mode selection
and whether a candidate plan requires a particular subset of the team.

## Phase 9 design rule

The responsibility split is:

1. Strategy: what future board or endgame do we want, and what resources can we spend?
2. Tactics: which bounded candidate actions can advance that plan against plausible replies?
3. Showdown: what mechanically happens in each exact branch?

PR #56 introduced the read-only strategic state and trade-assessment primitives.

PR #57 adds explicit `StrategicPlan` generation and posterior-aware plan ranking. Plans can
express objectives such as exploiting Trick Room, stalling opposing Tailwind, preserving a
unique resource, or neutralizing a boosted threat. The ranking remains read-only and does
not choose a Showdown command.
