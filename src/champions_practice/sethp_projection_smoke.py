"""Pinned-runtime regression for public -sethp projection consistency."""

from __future__ import annotations

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import BeliefParticle, condition_particles
from champions_practice.search_worker import ShowdownSearchWorker

PREVIEW = "team 1234"
SEED = "1,2,3,4"

TARGET_TEAM = """Snorlax
Ability: Thick Fat
Level: 50
Serious Nature
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk
"""

PAIN_SPLIT_TEAM = """Mimikyu
Ability: Disguise
Level: 50
Serious Nature
- Pain Split
- Sleep Talk

Shuckle
Ability: Sturdy
Level: 50
Serious Nature
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk
"""

TARGET_TURN = "move sleeptalk, move sleeptalk"
PAIN_SPLIT_TURN = "move painsplit +1, move sleeptalk"
TARGET_SWITCH_OUT = "switch 3, move sleeptalk"
TARGET_SWITCH_BACK = "switch 1, move sleeptalk"
OBSERVER_WAIT = "move sleeptalk, move sleeptalk"


def _previews(view: dict) -> dict[str, list[str]]:
    return {
        "p1": list(view["opponent"]["preview_species"])
        if view["player"]["name"] == "Observer"
        else [pokemon["species"] for pokemon in view["player"]["team"]],
        "p2": [pokemon["species"] for pokemon in view["player"]["team"]]
        if view["player"]["name"] == "Observer"
        else list(view["opponent"]["preview_species"]),
    }


def _target_slot(viewer_side: str) -> str:
    opponent_side = "p2" if viewer_side == "p1" else "p1"
    return f"{opponent_side}a"


def _sethp_percent(view: dict, *, target_slot: str) -> float:
    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        raise SystemExit("ERROR: public view omitted public_event_delta")
    events = delta.get("events")
    if not isinstance(events, list):
        raise SystemExit("ERROR: public event delta omitted events")

    for event in events:
        if (
            isinstance(event, list)
            and len(event) >= 3
            and event[0] == "-sethp"
            and event[1] == target_slot
        ):
            hp = str(event[2]).split(" ", 1)[0]
            current, maximum = hp.split("/", 1)
            return float(current) / float(maximum) * 100.0
    raise SystemExit("ERROR: Pain Split target -sethp event was not preserved")


def _snorlax_revealed(view: dict) -> dict:
    return next(
        pokemon
        for pokemon in view["opponent"]["revealed"]
        if pokemon.get("species") == "Snorlax"
    )


def _snorlax_belief_hp(view: dict) -> float | None:
    belief = build_public_opponent_belief(view)
    return next(
        pokemon.hp_percent
        for pokemon in belief.pokemon
        if pokemon.species == "Snorlax"
    )


def _exact_snorlax_hp(state: dict, *, target_side: str) -> tuple[int, int]:
    side_index = 0 if target_side == "p1" else 1
    sides = state.get("sides")
    if not isinstance(sides, list) or len(sides) <= side_index:
        raise SystemExit("ERROR: authoritative state omitted target side")
    pokemon = sides[side_index].get("pokemon")
    if not isinstance(pokemon, list) or not pokemon:
        raise SystemExit("ERROR: authoritative state omitted Snorlax")
    hp = pokemon[0].get("hp")
    maxhp = pokemon[0].get("maxhp")
    if not isinstance(hp, int) or not isinstance(maxhp, int):
        raise SystemExit("ERROR: authoritative state omitted Snorlax HP")
    return hp, maxhp


def _assert_projection(
    view: dict,
    *,
    viewer_side: str,
    expected_hp: float,
    active: bool,
) -> None:
    revealed_hp = _snorlax_revealed(view).get("hp_percent")
    belief_hp = _snorlax_belief_hp(view)

    if revealed_hp != expected_hp:
        raise SystemExit(
            "ERROR: revealed Snorlax HP disagrees with visible -sethp: "
            f"expected={expected_hp}, revealed={revealed_hp}"
        )
    if belief_hp != expected_hp:
        raise SystemExit(
            "ERROR: PublicOpponentBelief HP disagrees with visible -sethp: "
            f"expected={expected_hp}, belief={belief_hp}"
        )

    active_snorlax = next(
        (
            pokemon
            for pokemon in view["opponent"]["active"]
            if isinstance(pokemon, dict)
            and pokemon.get("base_species") == "Snorlax"
        ),
        None,
    )
    if active:
        if active_snorlax is None:
            raise SystemExit("ERROR: expected Snorlax to be publicly active")
        if active_snorlax.get("hp_percent") != expected_hp:
            raise SystemExit(
                "ERROR: active Snorlax HP disagrees with visible -sethp: "
                f"expected={expected_hp}, active={active_snorlax.get('hp_percent')}"
            )
    elif active_snorlax is not None:
        raise SystemExit("ERROR: expected Snorlax to be publicly benched")

    # The viewer side itself is intentionally unused here: this assertion operates
    # only on the viewer's opponent projection and therefore exercises both p1/p2
    # channel orientations when the fixture is mirrored.
    if viewer_side not in {"p1", "p2"}:
        raise SystemExit("ERROR: invalid viewer side")


def _run_orientation(
    worker: ShowdownSearchWorker,
    *,
    viewer_side: str,
) -> tuple[float, tuple[int, int]]:
    if viewer_side == "p2":
        p1_team = TARGET_TEAM
        p2_team = PAIN_SPLIT_TEAM
        p1_name = "Target"
        p2_name = "Observer"
        p1_turn = TARGET_TURN
        p2_turn = PAIN_SPLIT_TURN
        target_side = "p1"
    elif viewer_side == "p1":
        p1_team = PAIN_SPLIT_TEAM
        p2_team = TARGET_TEAM
        p1_name = "Observer"
        p2_name = "Target"
        p1_turn = PAIN_SPLIT_TURN
        p2_turn = TARGET_TURN
        target_side = "p2"
    else:
        raise ValueError("viewer_side must be p1 or p2")

    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=p1_team,
        p2_team=p2_team,
        p1_name=p1_name,
        p2_name=p2_name,
        seed=SEED,
    )
    session_id = started["session_id"]
    try:
        worker.choose_session(
            session_id,
            p1_choice=PREVIEW,
            p2_choice=PREVIEW,
        )
        before = worker.session_view(session_id, side=viewer_side)["view"]
        before_state = worker.session_snapshot(session_id)["state"]

        worker.choose_session(
            session_id,
            p1_choice=p1_turn,
            p2_choice=p2_turn,
        )
        after = worker.session_view(session_id, side=viewer_side)["view"]
        authoritative_state = worker.session_snapshot(session_id)["state"]

        target_slot = _target_slot(viewer_side)
        expected_hp = _sethp_percent(after, target_slot=target_slot)
        _assert_projection(
            after,
            viewer_side=viewer_side,
            expected_hp=expected_hp,
            active=True,
        )

        previews = _previews(before)
        ai_choice = p1_turn if viewer_side == "p1" else p2_turn
        opponent_choice = p2_turn if viewer_side == "p1" else p1_turn
        update = condition_particles(
            worker,
            particles=(
                BeliefParticle(
                    before_state,
                    1.0,
                    world_id=f"sethp-{viewer_side}",
                    history_id="before-pain-split",
                ),
            ),
            ai_side=viewer_side,
            ai_choice=ai_choice,
            actual_public_view=after,
            previous_public_view=before,
            resolved_opponent_choice=opponent_choice,
            previews=previews,
        )
        if not update.particles:
            raise SystemExit(
                "ERROR: correct Pain Split replay particle was rejected"
            )

        authoritative_hp = _exact_snorlax_hp(
            authoritative_state,
            target_side=target_side,
        )
        retained_hp = {
            _exact_snorlax_hp(particle.state, target_side=target_side)
            for particle in update.particles
        }
        if retained_hp != {authoritative_hp}:
            raise SystemExit(
                "ERROR: Pain Split conditioning retained wrong exact Snorlax HP: "
                f"authoritative={authoritative_hp}, retained={sorted(retained_hp)}"
            )

        if target_side == "p1":
            switch_out_p1 = TARGET_SWITCH_OUT
            switch_out_p2 = OBSERVER_WAIT
            switch_back_p1 = TARGET_SWITCH_BACK
            switch_back_p2 = OBSERVER_WAIT
        else:
            switch_out_p1 = OBSERVER_WAIT
            switch_out_p2 = TARGET_SWITCH_OUT
            switch_back_p1 = OBSERVER_WAIT
            switch_back_p2 = TARGET_SWITCH_BACK

        worker.choose_session(
            session_id,
            p1_choice=switch_out_p1,
            p2_choice=switch_out_p2,
        )
        benched = worker.session_view(session_id, side=viewer_side)["view"]
        _assert_projection(
            benched,
            viewer_side=viewer_side,
            expected_hp=expected_hp,
            active=False,
        )

        worker.choose_session(
            session_id,
            p1_choice=switch_back_p1,
            p2_choice=switch_back_p2,
        )
        returned = worker.session_view(session_id, side=viewer_side)["view"]
        _assert_projection(
            returned,
            viewer_side=viewer_side,
            expected_hp=expected_hp,
            active=True,
        )

        return expected_hp, authoritative_hp
    finally:
        worker.close_session(session_id)


def main() -> None:
    with ShowdownSearchWorker() as worker:
        p2_hp, p2_exact = _run_orientation(worker, viewer_side="p2")
        p1_hp, p1_exact = _run_orientation(worker, viewer_side="p1")

    print("Public -sethp projection consistency")
    print(f"p2 viewer Pain Split HP: {p2_hp:.1f}% exact={p2_exact[0]}/{p2_exact[1]}")
    print(f"p1 viewer Pain Split HP: {p1_hp:.1f}% exact={p1_exact[0]}/{p1_exact[1]}")
    print("Active/revealed/PublicOpponentBelief agree: YES")
    print("Benched HP persists after switch: YES")
    print("Returned active HP remains consistent: YES")
    print("Correct exact replay particle retained: YES")
    print("RESULT: public -sethp evidence and public HP summaries are coherent")


if __name__ == "__main__":
    main()
