"""Pinned-runtime regression for selected-command versus execution evidence."""

from __future__ import annotations

import copy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
)
from champions_practice.search_worker import ShowdownSearchWorker

SESSION_SEED = "sodium,10000001100000021000000310000004"
PREVIEW = "team 1234"
TURN_ONE_P1 = "move haze, move protect"
TURN_ONE_P2 = "move nuzzle +1, move protect"
TURN_TWO_P1 = "move haze, move protect"
TURN_TWO_P2 = "move protect, move protect"

P1_TEAM = """Murkrow
Ability: Prankster
Level: 50
Careful Nature
- Haze
- Protect
- Tailwind
- Foul Play

Sneasler
Ability: Unburden
Level: 50
Adamant Nature
- Close Combat
- Dire Claw
- Rock Slide
- Protect

Gardevoir
Ability: Trace
Level: 50
Modest Nature
- Psychic
- Hyper Voice
- Mystical Fire
- Protect

Rillaboom
Ability: Grassy Surge
Level: 50
Careful Nature
- Grassy Glide
- Wood Hammer
- High Horsepower
- Protect
"""

P2_TEAM = """Pikachu
Ability: Static
Level: 50
Timid Nature
- Nuzzle
- Protect
- Thunderbolt
- Fake Out

Indeedee-F
Ability: Synchronize
Level: 50
Relaxed Nature
- Psychic
- Follow Me
- Trick Room
- Protect

Armarouge
Ability: Flash Fire
Level: 50
Modest Nature
- Psychic
- Armor Cannon
- Wide Guard
- Protect

Rillaboom
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
        index + 0x1001,
        index + 0x2001,
        index + 0x3001,
        index + 0x4001,
    )
    return "sodium," + "".join(f"{value:08x}" for value in values)


def _execution_actions(view: dict) -> list[dict]:
    delta = view.get("public_execution_delta")
    if not isinstance(delta, dict):
        return []
    actions = delta.get("actions")
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, dict)]


def _haze_outcome(view: dict) -> str | None:
    for action in _execution_actions(view):
        if (
            action.get("side") == "opponent"
            and action.get("slot") == 1
            and action.get("outcome") == "executed"
            and action.get("move") == "haze"
        ):
            return "executed"
        if (
            action.get("side") == "opponent"
            and action.get("slot") == 1
            and action.get("outcome") == "prevented"
            and action.get("reason") == "par"
        ):
            return "prevented"
    return None


def _old_signature(view: dict) -> str:
    reduced = copy.deepcopy(view)
    # Recreate the historical selected-command-only boundary. #107 added the
    # execution ledger and #114 now independently preserves prevented/executed
    # mechanics in the public transition ledger.
    reduced.pop("public_execution_delta", None)
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
            after_setup = worker.session_view(session_id, side="p2")["view"]
            murkrow = next(
                pokemon
                for pokemon in after_setup["opponent"]["revealed"]
                if pokemon["species"] == "Murkrow"
            )
            if murkrow["status"] != "par":
                raise SystemExit(
                    "ERROR: execution-evidence fixture failed to paralyze Murkrow"
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

        by_outcome: dict[str, list[dict]] = {
            "executed": [],
            "prevented": [],
        }
        for branch in resolved:
            view = branch.get("view")
            if not isinstance(view, dict):
                raise SystemExit("ERROR: Haze branch returned no public view")
            outcome = _haze_outcome(view)
            if outcome in by_outcome:
                by_outcome[outcome].append(branch)

        if not by_outcome["executed"] or not by_outcome["prevented"]:
            raise SystemExit(
                "ERROR: fixture did not produce both executed and full-paralysis "
                f"Haze outcomes: executed={len(by_outcome['executed'])} "
                f"prevented={len(by_outcome['prevented'])}"
            )

        old_executed = {
            _old_signature(branch["view"])
            for branch in by_outcome["executed"]
        }
        old_prevented = {
            _old_signature(branch["view"])
            for branch in by_outcome["prevented"]
        }
        if not old_executed.intersection(old_prevented):
            raise SystemExit(
                "ERROR: fixture no longer reproduces selected-command collision"
            )

        new_executed = {
            public_observation_signature(branch["view"])
            for branch in by_outcome["executed"]
        }
        new_prevented = {
            public_observation_signature(branch["view"])
            for branch in by_outcome["prevented"]
        }
        if new_executed.intersection(new_prevented):
            raise SystemExit(
                "ERROR: execution-authoritative signatures still collide"
            )

        actual_view = by_outcome["executed"][0]["view"]
        update = condition_particles(
            worker,
            particles=(
                BeliefParticle(
                    snapshot,
                    1.0,
                    world_id="haze-world",
                    history_id="pre-haze",
                ),
            ),
            ai_side="p2",
            ai_choice=TURN_TWO_P2,
            actual_public_view=actual_view,
            previous_public_view=after_setup,
            rng_seeds=seeds,
            previews=previews,
        )
        if not update.particles:
            raise SystemExit(
                "ERROR: execution-authoritative conditioning eliminated all branches"
            )

        for particle in update.particles:
            view = worker.state_view(
                state=particle.state,
                side="p2",
                previews=previews,
            )
            if _haze_outcome(view) != "executed":
                raise SystemExit(
                    "ERROR: conditioning retained a full-paralysis branch against "
                    "publicly observed Haze execution"
                )

    print("Authoritative public action execution conditioning")
    print(
        "64 sampled futures: "
        f"executed={len(by_outcome['executed'])}, "
        f"prevented={len(by_outcome['prevented'])}"
    )
    print("Old selected-command signatures collide across outcomes: YES")
    print("Execution-authoritative signatures collide across outcomes: NO")
    print(f"Conditioning matches for observed execution: {update.matched}")
    print(f"Posterior states after conditioning: {len(update.particles)}")
    print("RESULT: selected commands no longer substitute for execution evidence")


if __name__ == "__main__":
    main()
