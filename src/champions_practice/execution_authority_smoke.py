"""Pinned-runtime regressions for ordered, both-side execution authority."""

from __future__ import annotations

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

ORDER_HUMAN_TEAM = """Snorlax
Ability: Thick Fat
Level: 50
- Tackle
- Sleep Talk

Slowbro
Ability: Own Tempo
Level: 50
- Growl
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
- Sleep Talk
"""

ORDER_AI_TEAM = """Lucario
Ability: Inner Focus
Level: 50
- Sleep Talk
- Copycat

Dusclops
Ability: Pressure
Level: 50
EVs: 32 Spe
Timid Nature
- Sleep Talk

Indeedee-F
Ability: Synchronize
Level: 50
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
- Sleep Talk
"""

CALLED_HUMAN_TEAM = """Vaporeon
Ability: Water Absorb
Level: 50
IVs: 0 Spe
- Haze
- Sleep Talk

Amoonguss
Ability: Effect Spore
Level: 50
- Spore
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
- Sleep Talk

Armarouge
Ability: Flash Fire
Level: 50
- Sleep Talk
"""

CALLED_AI_TEAM = """Sandslash
Ability: Sand Veil
Level: 50
- Sleep Talk
- Defense Curl
- Swords Dance
- Rollout

Indeedee-F
Ability: Synchronize
Level: 50
- Sleep Talk

Rillaboom
Ability: Overgrow
Level: 50
- Sleep Talk

Metagross
Ability: Clear Body
Level: 50
- Sleep Talk
"""


def _previews(view: dict) -> dict[str, list[str]]:
    return {
        "p1": list(view["opponent"]["preview_species"]),
        "p2": [pokemon["species"] for pokemon in view["player"]["team"]],
    }


def _last_move_id(state: dict) -> str:
    last_move = state.get("lastMove")
    if not isinstance(last_move, dict):
        return ""
    value = str(last_move.get("move") or "").lower()
    if "tackle" in value:
        return "tackle"
    if "growl" in value:
        return "growl"
    return value


def _has_defense_curl(state: dict) -> bool:
    sides = state.get("sides")
    if not isinstance(sides, list) or len(sides) < 2:
        return False
    pokemon = sides[1].get("pokemon")
    if not isinstance(pokemon, list) or not pokemon:
        return False
    volatiles = pokemon[0].get("volatiles")
    return isinstance(volatiles, dict) and "defensecurl" in volatiles


def _log_contains(state: dict, token: str) -> bool:
    log = state.get("log")
    return isinstance(log, list) and any(token in str(line) for line in log[-32:])


def _execution_actions(view: dict) -> list[dict]:
    delta = view.get("public_execution_delta")
    if not isinstance(delta, dict):
        return []
    actions = delta.get("actions")
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, dict)]


def _ordered_last_move_regression(worker: ShowdownSearchWorker) -> None:
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=ORDER_HUMAN_TEAM,
        p2_team=ORDER_AI_TEAM,
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
        state = worker.session_snapshot(session_id)["state"]
        previews = _previews(before)
    finally:
        worker.close_session(session_id)

    human_choice = "move tackle +2, move growl"
    ai_choice = "move sleeptalk, move sleeptalk"
    branches = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": human_choice,
                "p2_choice": ai_choice,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
                "rng_seed": seed,
            }
            for seed in SEEDS
        ],
    )

    by_signature: dict[str, set[str]] = defaultdict(set)
    by_last_move: dict[str, dict] = {}
    for branch in branches:
        view = branch.get("view")
        exact_state = branch.get("state")
        if not isinstance(view, dict) or not isinstance(exact_state, dict):
            raise SystemExit("ERROR: order fixture branch omitted state/view")
        last_move = _last_move_id(exact_state)
        by_signature[public_observation_signature(view)].add(last_move)
        by_last_move.setdefault(last_move, branch)

    if "tackle" not in by_last_move or "growl" not in by_last_move:
        raise SystemExit(
            "ERROR: order fixture did not produce both Tackle/Growl lastMove states"
        )
    collisions = [
        values for values in by_signature.values() if len(values) > 1
    ]
    if collisions:
        raise SystemExit(
            "ERROR: ordered execution signature retained conflicting lastMove states"
        )

    actual = by_last_move["tackle"]
    update = condition_particles(
        worker,
        particles=(
            BeliefParticle(
                state,
                1.0,
                world_id="ordered-execution",
                history_id="before-speed-tie",
            ),
        ),
        ai_side="p2",
        ai_choice=ai_choice,
        actual_public_view=actual["view"],
        previous_public_view=before,
        resolved_opponent_choice=human_choice,
        rng_seeds=SEEDS,
        previews=previews,
    )
    if not update.particles:
        raise SystemExit(
            "ERROR: ordered execution conditioning eliminated every valid branch"
        )
    wrong = [
        particle
        for particle in update.particles
        if _last_move_id(particle.state) != "tackle"
    ]
    if wrong:
        raise SystemExit(
            "ERROR: conditioning retained a publicly contradicted lastMove history"
        )

    tackle_actions = _execution_actions(actual["view"])
    growl_actions = _execution_actions(by_last_move["growl"]["view"])
    tackle_order = [
        (action.get("side"), action.get("slot"), action.get("move"))
        for action in tackle_actions
    ]
    growl_order = [
        (action.get("side"), action.get("slot"), action.get("move"))
        for action in growl_actions
    ]
    if tackle_order == growl_order:
        raise SystemExit(
            "ERROR: execution ledger still erased public speed-tie move order"
        )


def _called_move_regression(worker: ShowdownSearchWorker) -> None:
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=CALLED_HUMAN_TEAM,
        p2_team=CALLED_AI_TEAM,
        seed="1,2,3,4",
    )
    session_id = started["session_id"]
    try:
        worker.choose_session(
            session_id,
            p1_choice=PREVIEW,
            p2_choice=PREVIEW,
        )
        worker.choose_session(
            session_id,
            p1_choice="move sleeptalk, move spore +1",
            p2_choice="move sleeptalk, move sleeptalk",
        )
        before = worker.session_view(session_id, side="p2")["view"]
        state = worker.session_snapshot(session_id)["state"]
        previews = _previews(before)
    finally:
        worker.close_session(session_id)

    human_choice = "move haze, move sleeptalk"
    ai_choice = "move sleeptalk, move sleeptalk"
    branches = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": human_choice,
                "p2_choice": ai_choice,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
                "rng_seed": seed,
            }
            for seed in SEEDS
        ],
    )

    by_signature: dict[str, set[bool]] = defaultdict(set)
    actual = None
    wrong = None
    wrong_seed = None
    for seed, branch in zip(SEEDS, branches, strict=True):
        view = branch.get("view")
        exact_state = branch.get("state")
        if not isinstance(view, dict) or not isinstance(exact_state, dict):
            raise SystemExit("ERROR: called-move fixture branch omitted state/view")
        curled = _has_defense_curl(exact_state)
        by_signature[public_observation_signature(view)].add(curled)
        if curled and actual is None:
            actual = branch
        if (
            not curled
            and wrong is None
            and _log_contains(exact_state, "|Swords Dance|")
        ):
            wrong = branch
            wrong_seed = seed

    if actual is None or wrong is None or wrong_seed is None:
        raise SystemExit(
            "ERROR: called-move fixture did not produce Defense Curl and Swords Dance"
        )
    collisions = [
        values for values in by_signature.values() if len(values) > 1
    ]
    if collisions:
        raise SystemExit(
            "ERROR: execution signature retained conflicting called-move histories"
        )

    actions = _execution_actions(actual["view"])
    called_index = next(
        (
            index
            for index, action in enumerate(actions)
            if action.get("side") == "player"
            and action.get("slot") == 1
            and action.get("move") == "defensecurl"
            and action.get("source") == "called"
            and "[from]:move:sleeptalk" in action.get("provenance", [])
        ),
        None,
    )
    haze_index = next(
        (
            index
            for index, action in enumerate(actions)
            if action.get("side") == "opponent"
            and action.get("slot") == 1
            and action.get("move") == "haze"
        ),
        None,
    )
    if called_index is None:
        raise SystemExit(
            "ERROR: called Defense Curl missing provenance in execution ledger: "
            f"{actions!r}"
        )
    if haze_index is None:
        raise SystemExit(
            "ERROR: opponent Haze missing from both-side execution ledger: "
            f"{actions!r}"
        )
    if called_index >= haze_index:
        raise SystemExit(
            "ERROR: execution ledger did not preserve Defense Curl before Haze: "
            f"{actions!r}"
        )

    update = condition_particles(
        worker,
        particles=(
            BeliefParticle(
                state,
                1.0,
                world_id="called-execution",
                history_id="before-sleep-talk",
            ),
        ),
        ai_side="p2",
        ai_choice=ai_choice,
        actual_public_view=actual["view"],
        previous_public_view=before,
        resolved_opponent_choice=human_choice,
        rng_seeds=SEEDS,
        previews=previews,
    )
    if not update.particles:
        raise SystemExit(
            "ERROR: called-move conditioning eliminated every valid branch"
        )
    if any(not _has_defense_curl(particle.state) for particle in update.particles):
        raise SystemExit(
            "ERROR: conditioning retained a wrong called-move persistent state"
        )

    opponent_view = worker.state_view(
        state=actual["state"],
        side="p1",
        previews=previews,
    )
    sandslash = next(
        (
            pokemon
            for pokemon in opponent_view["opponent"]["revealed"]
            if pokemon.get("species") == "Sandslash"
        ),
        None,
    )
    if sandslash is None:
        raise SystemExit("ERROR: Sandslash was not publicly revealed")
    learned_moves = set(sandslash.get("moves") or [])
    if "sleeptalk" not in learned_moves or "defensecurl" in learned_moves:
        raise SystemExit(
            "ERROR: called move was confused with learned moveset disclosure"
        )

    engine = BeliefDecisionEngine(
        ".",
        battle_format=CHAMPIONS_FORMAT,
        ai_team=CALLED_AI_TEAM,
        opponent_priors={},
    )
    original = BeliefParticle(
        state,
        1.0,
        world_id="called-execution",
        history_id="before-sleep-talk",
    )
    engine.particles = (original,)
    engine.previews = previews
    engine.last_public_view = before
    engine._particle_seed = lambda: wrong_seed
    observed = engine.observe_public_turn(
        decision=BeliefDecision(
            choice=ai_choice,
            mode="fixture",
            particle_count=1,
            candidate_count=1,
            branch_count=1,
            elapsed_seconds=0.0,
        ),
        view=actual["view"],
        resolved_opponent_choice=human_choice,
    )
    if observed.matched_branches != 0:
        raise SystemExit(
            "ERROR: persistent engine accepted a publicly wrong called-move branch"
        )
    if not engine.degraded or not engine.pending_observations:
        raise SystemExit(
            "ERROR: persistent engine declared wrong called-move history healthy"
        )
    if engine.particles != (original,):
        raise SystemExit(
            "ERROR: persistent engine replaced last-good particles after mismatch"
        )


def main() -> None:
    with ShowdownSearchWorker() as worker:
        _ordered_last_move_regression(worker)
        _called_move_regression(worker)

    print("Ordered, both-side public execution authority")
    print("Copycat/lastMove contradiction rejected: YES")
    print("Sleep Talk called-move contradiction rejected: YES")
    print("Called move kept separate from learned moveset disclosure: YES")
    print("Persistent engine fails closed on forced wrong called history: YES")
    print("RESULT: public execution evidence preserves mechanics-relevant history")


if __name__ == "__main__":
    main()
