"""Pinned-runtime regression for authoritative public mechanics event conditioning."""

from __future__ import annotations

import copy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
)
from champions_practice.search_worker import ShowdownSearchWorker

SESSION_SEED = "sodium,00000001000000020000000300000004"
PREVIEW = "team 1234"
TURN_ONE_P1 = "move substitute, move protect"
TURN_ONE_P2 = "move protect, move protect"
TURN_TWO_P1 = "move sleeptalk, move protect"
TURN_TWO_P2 = "move psychic +1, move protect"

P1_TEAM = """Snorlax
Ability: Thick Fat
Level: 50
Calm Nature
- Substitute
- Sleep Talk
- Protect
- Body Slam

Sneasler @ Psychic Seed
Ability: Unburden
Level: 50
Adamant Nature
- Close Combat
- Dire Claw
- Rock Slide
- Protect

Gardevoir @ Gardevoirite
Ability: Trace
Level: 50
Modest Nature
- Expanding Force
- Hyper Voice
- Mystical Fire
- Protect

Rillaboom @ Sitrus Berry
Ability: Grassy Surge
Level: 50
Careful Nature
- Grassy Glide
- Wood Hammer
- High Horsepower
- Protect
"""

P2_TEAM = """Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Psychic
- Armor Cannon
- Wide Guard
- Protect

Sneasler @ Psychic Seed
Ability: Unburden
Level: 50
Adamant Nature
- Close Combat
- Dire Claw
- Rock Slide
- Protect

Gardevoir @ Gardevoirite
Ability: Trace
Level: 50
Modest Nature
- Expanding Force
- Hyper Voice
- Mystical Fire
- Protect

Rillaboom @ Sitrus Berry
Ability: Grassy Surge
Level: 50
Careful Nature
- Grassy Glide
- Wood Hammer
- High Horsepower
- Protect
"""


def _rng_seed(index: int) -> str:
    values = (
        index + 1,
        index + 0x101,
        index + 0x201,
        index + 0x301,
    )
    return "sodium," + "".join(f"{value:08x}" for value in values)


def _events(view: dict) -> list[list[str]]:
    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        return []
    events = delta.get("events")
    return events if isinstance(events, list) else []


def _substitute_outcome(view: dict) -> str | None:
    for event in _events(view):
        if (
            len(event) >= 3
            and event[0] == "-end"
            and event[1] == "p1a"
            and event[2] == "substitute"
        ):
            return "broken"
    for event in _events(view):
        if (
            len(event) >= 3
            and event[0] == "-activate"
            and event[1] == "p1a"
            and event[2] == "move:substitute"
        ):
            return "survived"
    return None


def _has_crit(view: dict) -> bool:
    return any(event and event[0] == "-crit" for event in _events(view))


def _old_signature(view: dict) -> str:
    reduced = copy.deepcopy(view)
    reduced.pop("public_event_delta", None)
    return public_observation_signature(reduced)


def main() -> None:
    seeds = tuple(_rng_seed(index) for index in range(64))

    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=P1_TEAM,
            p2_team=P2_TEAM,
            p1_name="Human",
            p2_name="Belief AI",
            seed=SESSION_SEED,
        )
        session_id = started["session_id"]
        try:
            worker.choose_session(
                session_id,
                p1_choice=PREVIEW,
                p2_choice=PREVIEW,
            )
            preview_view = worker.session_view(session_id, side="p2")["view"]
            previews = {
                "p1": preview_view["opponent"]["preview_species"],
                "p2": [
                    pokemon["species"]
                    for pokemon in preview_view["player"]["team"]
                ],
            }

            worker.choose_session(
                session_id,
                p1_choice=TURN_ONE_P1,
                p2_choice=TURN_ONE_P2,
            )
            snapshot = worker.session_snapshot(session_id)["state"]
        finally:
            worker.close_session(session_id)

        branches = [
            {
                "p1_choice": TURN_TWO_P1,
                "p2_choice": TURN_TWO_P2,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
                "rng_seed": seed,
            }
            for seed in seeds
        ]
        resolved = worker.branch_many(state=snapshot, branches=branches)

        by_outcome: dict[str, list[dict]] = {"broken": [], "survived": []}
        for branch in resolved:
            view = branch.get("view")
            if not isinstance(view, dict):
                raise SystemExit("ERROR: Substitute branch returned no public view")
            outcome = _substitute_outcome(view)
            if outcome in by_outcome:
                by_outcome[outcome].append(branch)

        if not by_outcome["broken"] or not by_outcome["survived"]:
            raise SystemExit(
                "ERROR: fixture did not produce both broken and surviving Substitute "
                f"outcomes: broken={len(by_outcome['broken'])} "
                f"survived={len(by_outcome['survived'])}"
            )

        old_broken = {
            _old_signature(branch["view"])
            for branch in by_outcome["broken"]
        }
        old_survived = {
            _old_signature(branch["view"])
            for branch in by_outcome["survived"]
        }
        if not old_broken.intersection(old_survived):
            raise SystemExit(
                "ERROR: fixture no longer reproduces the reduced-signature collision"
            )

        new_broken = {
            public_observation_signature(branch["view"])
            for branch in by_outcome["broken"]
        }
        new_survived = {
            public_observation_signature(branch["view"])
            for branch in by_outcome["survived"]
        }
        if new_broken.intersection(new_survived):
            raise SystemExit(
                "ERROR: authoritative public event signatures still collide across "
                "Substitute outcomes"
            )

        actual_branch = next(
            (
                branch
                for branch in by_outcome["broken"]
                if not _has_crit(branch["view"])
            ),
            by_outcome["broken"][0],
        )
        actual_view = actual_branch["view"]

        update = condition_particles(
            worker,
            particles=(
                BeliefParticle(
                    snapshot,
                    1.0,
                    world_id="substitute-world",
                    history_id="pre-hit",
                ),
            ),
            ai_side="p2",
            ai_choice=TURN_TWO_P2,
            actual_public_view=actual_view,
            resolved_opponent_choice=TURN_TWO_P1,
            rng_seeds=seeds,
            previews=previews,
        )
        if not update.particles:
            raise SystemExit(
                "ERROR: event-authoritative conditioning eliminated every branch"
            )

        for particle in update.particles:
            view = worker.state_view(
                state=particle.state,
                side="p2",
                previews=previews,
            )
            if _substitute_outcome(view) != "broken":
                raise SystemExit(
                    "ERROR: conditioning retained a Substitute-survived branch "
                    "against a publicly observed break"
                )

    print("Authoritative public mechanics event conditioning")
    print(
        "64 sampled futures: "
        f"broken={len(by_outcome['broken'])}, "
        f"survived={len(by_outcome['survived'])}"
    )
    print("Reduced state signatures collide across outcomes: YES")
    print("Event-authoritative signatures collide across outcomes: NO")
    print(f"Conditioning matches for observed break: {update.matched}")
    print(f"Posterior states after conditioning: {len(update.particles)}")
    print("RESULT: publicly visible Substitute transitions constrain the posterior")


if __name__ == "__main__":
    main()
