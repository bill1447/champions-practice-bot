"""Pinned-runtime regression for quantitative public transition authority."""

from __future__ import annotations

import copy
import json
from collections import defaultdict

from champions_practice.belief_controller import BeliefDecision, BeliefDecisionEngine
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
)
from champions_practice.search_worker import ShowdownSearchWorker

PREVIEW = "team 1234"
SEEDS = tuple(f"{index},2,3,4" for index in range(1, 129))
FUTURE_SEED = "99,2,3,4"

HUMAN_TURN = "move bulletseed +1, move sleeptalk"
AI_TURN = "move rest, move sleeptalk"
FUTURE_HUMAN_TURN = "move sleeptalk, move sleeptalk"
FUTURE_AI_TURN = "move ragefist +1, move sleeptalk"

HUMAN_TEAM = """Jumpluff
Ability: Chlorophyll
Level: 50
Serious Nature
- Bullet Seed
- Sleep Talk
- Protect
- Splash

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

AI_TEAM = """Annihilape
Ability: Defiant
Level: 50
Serious Nature
- Rest
- Rage Fist
- Sleep Talk
- Protect

Snorlax
Ability: Thick Fat
Level: 50
Serious Nature
- Sleep Talk

Indeedee-F
Ability: Synchronize
Level: 50
Serious Nature
- Sleep Talk

Metagross
Ability: Clear Body
Level: 50
Serious Nature
- Sleep Talk
"""

PRIVACY_HUMAN_A = """Snorlax @ Choice Band
Ability: Thick Fat
Level: 50
EVs: 252 HP
Serious Nature
- Sleep Talk
- Earthquake

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

PRIVACY_HUMAN_B = """Snorlax @ Expert Belt
Ability: Thick Fat
Level: 50
EVs: 4 HP
Serious Nature
- Sleep Talk
- Body Slam

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

PRIVACY_AI_TEAM = """Indeedee-F @ Choice Specs
Ability: Synchronize
Level: 50
Serious Nature
- Sleep Talk
- Shadow Ball

Armarouge
Ability: Flash Fire
Level: 50
Serious Nature
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
Serious Nature
- Sleep Talk

Metagross
Ability: Clear Body
Level: 50
Serious Nature
- Sleep Talk
"""

PRIVACY_HUMAN_TURN = "move sleeptalk, move sleeptalk"
PRIVACY_AI_TURN = "move sleeptalk, move sleeptalk"


def _previews(view: dict) -> dict[str, list[str]]:
    return {
        "p1": list(view["opponent"]["preview_species"]),
        "p2": [pokemon["species"] for pokemon in view["player"]["team"]],
    }


def _events(view: dict) -> list[list[str]]:
    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        return []
    events = delta.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, list)]


def _hitcount(view: dict) -> int | None:
    for event in _events(view):
        if len(event) >= 3 and event[0] == "-hitcount":
            try:
                return int(event[2])
            except (TypeError, ValueError):
                return None
    return None


def _hitcount_event(view: dict) -> list[str] | None:
    return next(
        (
            event
            for event in _events(view)
            if len(event) >= 3 and event[0] == "-hitcount"
        ),
        None,
    )


def _times_attacked(state: dict) -> int:
    sides = state.get("sides")
    if not isinstance(sides, list) or len(sides) < 2:
        raise SystemExit("ERROR: exact state has no AI side")
    pokemon = sides[1].get("pokemon")
    if not isinstance(pokemon, list) or not pokemon:
        raise SystemExit("ERROR: exact state has no Annihilape")
    value = pokemon[0].get("timesAttacked")
    if not isinstance(value, int):
        raise SystemExit("ERROR: exact state omitted Annihilape timesAttacked")
    return value


def _pokemon_hp(state: dict, *, side: int, index: int) -> tuple[int, int, bool]:
    sides = state.get("sides")
    if not isinstance(sides, list) or len(sides) <= side:
        raise SystemExit("ERROR: exact state omitted expected side")
    pokemon = sides[side].get("pokemon")
    if not isinstance(pokemon, list) or len(pokemon) <= index:
        raise SystemExit("ERROR: exact state omitted expected Pokemon")
    mon = pokemon[index]
    hp = mon.get("hp")
    maxhp = mon.get("maxhp")
    fainted = mon.get("fainted")
    if not isinstance(hp, int) or not isinstance(maxhp, int):
        raise SystemExit("ERROR: exact state omitted HP")
    return hp, maxhp, bool(fainted)


def _old_signature(view: dict) -> str:
    reduced = copy.deepcopy(view)
    reduced.pop("public_event_delta", None)
    return public_observation_signature(reduced)


def _future_rage_fist_result(
    worker: ShowdownSearchWorker,
    *,
    state: dict,
    previews: dict[str, list[str]],
) -> tuple[int, int, bool, int]:
    current = state
    initial_hp, maxhp, _ = _pokemon_hp(current, side=0, index=0)

    for turn_index in range(1, 5):
        resolved = worker.branch_many(
            state=current,
            branches=[
                {
                    "p1_choice": FUTURE_HUMAN_TURN,
                    "p2_choice": FUTURE_AI_TURN,
                    "include_state": True,
                    "view_side": "p2",
                    "previews": previews,
                    "rng_seed": FUTURE_SEED,
                }
            ],
        )
        if len(resolved) != 1 or not isinstance(resolved[0].get("state"), dict):
            raise SystemExit("ERROR: future Rage Fist branch omitted exact state")
        current = resolved[0]["state"]
        hp, current_maxhp, fainted = _pokemon_hp(current, side=0, index=0)
        if current_maxhp != maxhp:
            raise SystemExit("ERROR: Jumpluff max HP changed unexpectedly")
        if hp < initial_hp or fainted:
            return hp, maxhp, fainted, turn_index

    raise SystemExit("ERROR: Annihilape never reached its future Rage Fist action")


def _privacy_state(
    worker: ShowdownSearchWorker,
    human_team: str,
) -> dict:
    return worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=human_team,
        p2_team=PRIVACY_AI_TEAM,
        p1_preview=PREVIEW,
        p2_preview=PREVIEW,
        seed="7,8,9,10",
    )


def _privacy_regression(worker: ShowdownSearchWorker) -> None:
    states = (
        _privacy_state(worker, PRIVACY_HUMAN_A),
        _privacy_state(worker, PRIVACY_HUMAN_B),
    )
    branches = []
    for state in states:
        resolved = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": PRIVACY_HUMAN_TURN,
                    "p2_choice": PRIVACY_AI_TURN,
                    "include_state": True,
                    "view_side": "p2",
                    "rng_seed": "11,12,13,14",
                }
            ],
        )
        if len(resolved) != 1 or not isinstance(resolved[0].get("view"), dict):
            raise SystemExit("ERROR: privacy branch omitted public view")
        branches.append(resolved[0])

    left = branches[0]["view"]["public_event_delta"]
    right = branches[1]["view"]["public_event_delta"]
    if left != right:
        raise SystemExit(
            "ERROR: hidden opponent item/stat/moves changed public transition ledger"
        )

    p2_public = json.dumps(left, sort_keys=True).lower()
    for hidden in ("choiceband", "expertbelt", "earthquake", "bodyslam"):
        if hidden in p2_public:
            raise SystemExit(
                "ERROR: opponent hidden information leaked into p2 transition ledger: "
                f"{hidden}"
            )

    exact_state = branches[0]["state"]
    p2_view = branches[0]["view"]
    previews = {
        "p1": list(p2_view["opponent"]["preview_species"]),
        "p2": [pokemon["species"] for pokemon in p2_view["player"]["team"]],
    }
    p1_view = worker.state_view(
        state=exact_state,
        side="p1",
        previews=previews,
    )
    p1_public = json.dumps(p1_view["public_event_delta"], sort_keys=True).lower()
    for hidden in ("choicespecs", "shadowball"):
        if hidden in p1_public:
            raise SystemExit(
                "ERROR: opponent hidden information leaked into p1 transition ledger: "
                f"{hidden}"
            )


def _hitcount_regression(worker: ShowdownSearchWorker) -> tuple[int, int, int, int]:
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=HUMAN_TEAM,
        p2_team=AI_TEAM,
        p1_name="Human",
        p2_name="Belief AI",
        seed="1,2,3,4",
    )
    session_id = started["session_id"]
    try:
        worker.choose_session(
            session_id,
            p1_choice=PREVIEW,
            p2_choice=PREVIEW,
        )
        before = worker.session_view(session_id, side="p2")["view"]
        snapshot = worker.session_snapshot(session_id)["state"]
        previews = _previews(before)
    finally:
        worker.close_session(session_id)

    branches = worker.branch_many(
        state=snapshot,
        branches=[
            {
                "p1_choice": HUMAN_TURN,
                "p2_choice": AI_TURN,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
                "rng_seed": seed,
            }
            for seed in SEEDS
        ],
    )

    by_old_signature: dict[str, list[tuple[str, dict, int]]] = defaultdict(list)
    for seed, branch in zip(SEEDS, branches, strict=True):
        view = branch.get("view")
        state = branch.get("state")
        if not isinstance(view, dict) or not isinstance(state, dict):
            raise SystemExit("ERROR: hit-count fixture branch omitted state/view")
        count = _hitcount(view)
        if count is None:
            raise SystemExit("ERROR: Bullet Seed branch omitted public hit count")
        if _times_attacked(state) != count:
            raise SystemExit(
                "ERROR: Showdown hit-count evidence disagrees with timesAttacked"
            )
        by_old_signature[_old_signature(view)].append((seed, branch, count))

    collision = next(
        (
            group
            for group in by_old_signature.values()
            if 2 in {entry[2] for entry in group}
            and 5 in {entry[2] for entry in group}
        ),
        None,
    )
    if collision is None:
        counts = sorted(
            {
                entry[2]
                for group in by_old_signature.values()
                for entry in group
            }
        )
        raise SystemExit(
            "ERROR: fixture did not reproduce a reduced-view 2/5-hit collision: "
            f"counts={counts!r}"
        )

    actual_seed, actual, actual_count = next(
        entry for entry in collision if entry[2] == 2
    )
    wrong_seed, wrong, wrong_count = next(
        entry for entry in collision if entry[2] == 5
    )
    if actual_count != 2 or wrong_count != 5:
        raise SystemExit("ERROR: hit-count fixture selected wrong branches")

    actual_event = _hitcount_event(actual["view"])
    if actual_event is None:
        raise SystemExit("ERROR: actual branch lost hit-count event")
    if actual_event[:3] != ["-hitcount", "p2a", "2"]:
        raise SystemExit(
            "ERROR: hit-count event lost target/count authority: "
            f"{actual_event!r}"
        )
    if actual_event[3:] != [
        "[action]",
        "opponent",
        "1",
        "bulletseed",
        "selected",
    ]:
        raise SystemExit(
            "ERROR: hit-count event lost execution context: "
            f"{actual_event!r}"
        )

    if public_observation_signature(actual["view"]) == public_observation_signature(
        wrong["view"]
    ):
        raise SystemExit(
            "ERROR: quantitative public signatures still collide across hit counts"
        )

    update = condition_particles(
        worker,
        particles=(
            BeliefParticle(
                snapshot,
                1.0,
                world_id="hitcount-world",
                history_id="before-bullet-seed",
            ),
        ),
        ai_side="p2",
        ai_choice=AI_TURN,
        actual_public_view=actual["view"],
        previous_public_view=before,
        rng_seeds=SEEDS,
        previews=previews,
    )
    if not update.particles:
        raise SystemExit(
            "ERROR: quantitative conditioning eliminated every valid two-hit branch"
        )
    if any(_times_attacked(particle.state) != 2 for particle in update.particles):
        raise SystemExit(
            "ERROR: quantitative conditioning retained an incorrect timesAttacked"
        )

    engine = BeliefDecisionEngine(
        ".",
        battle_format=CHAMPIONS_FORMAT,
        ai_team=AI_TEAM,
        opponent_priors={},
    )
    original = BeliefParticle(
        snapshot,
        1.0,
        world_id="hitcount-world",
        history_id="before-bullet-seed",
    )
    engine.particles = (original,)
    engine.previews = previews
    engine.last_public_view = before
    engine._particle_seed = lambda: wrong_seed
    observed = engine.observe_public_turn(
        decision=BeliefDecision(
            choice=AI_TURN,
            mode="fixture",
            particle_count=1,
            candidate_count=1,
            branch_count=1,
            elapsed_seconds=0.0,
        ),
        view=actual["view"],
    )
    if observed.matched_branches != 0:
        raise SystemExit(
            "ERROR: persistent engine accepted a publicly wrong five-hit history"
        )
    if not engine.degraded or not engine.pending_observations:
        raise SystemExit(
            "ERROR: persistent engine declared wrong hit-count history healthy"
        )
    if engine.particles != (original,):
        raise SystemExit(
            "ERROR: persistent engine replaced last-good particles after mismatch"
        )

    two_hp, two_maxhp, two_fainted, two_turn = _future_rage_fist_result(
        worker,
        state=actual["state"],
        previews=previews,
    )
    five_hp, five_maxhp, five_fainted, five_turn = _future_rage_fist_result(
        worker,
        state=wrong["state"],
        previews=previews,
    )
    if two_maxhp != five_maxhp or two_turn != five_turn:
        raise SystemExit(
            "ERROR: future comparison did not preserve identical continuation timing"
        )
    if two_hp == five_hp and two_fainted == five_fainted:
        raise SystemExit(
            "ERROR: different public hit histories had no future Rage Fist consequence"
        )
    if two_hp <= five_hp:
        raise SystemExit(
            "ERROR: higher timesAttacked did not increase future Rage Fist damage"
        )

    return len(collision), update.matched, two_hp, five_hp


def main() -> None:
    with ShowdownSearchWorker() as worker:
        collision_size, matched, two_hp, five_hp = _hitcount_regression(worker)
        _privacy_regression(worker)

    print("Quantitative public transition authority")
    print(f"Reduced-view collision branches: {collision_size}")
    print(f"Conditioning matches for observed two-hit branch: {matched}")
    print("Wrong five-hit persistent history accepted: NO")
    print(f"Future Rage Fist Jumpluff HP: two-hit={two_hp}, five-hit={five_hp}")
    print("Hidden item/stat/move changes alter public transition ledger: NO")
    print("Unsupported public mechanics events fail closed: covered by unit test")
    print("RESULT: quantitative public mechanics evidence is conditioning authority")


if __name__ == "__main__":
    main()
