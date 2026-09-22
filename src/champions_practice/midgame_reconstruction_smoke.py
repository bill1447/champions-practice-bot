"""Integration smoke for replay-based midgame belief reconstruction."""

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_smoke import ORIGINAL_METAGROSS, _public_priors
from champions_practice.belief_worlds import (
    PublicTurnChoice,
    materialize_public_belief_worlds,
    reconstruct_midgame_belief_worlds,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"
AI_PREVIEW = "team 1235"
HUMAN_PREVIEW = "team 6412"
MIDGAME_HIDDEN_VARIANT_METAGROSS = """Metagross @ Metagrossite
Ability: Clear Body
Level: 50
EVs: 32 HP / 32 Def / 2 SpD
Careful Nature
- Psychic Fangs
- Bullet Punch
- Ice Punch
- Protect
"""


def _midgame_hidden_variant_team() -> str:
    variant = SMOKE_TEAM.replace(ORIGINAL_METAGROSS, MIDGAME_HIDDEN_VARIANT_METAGROSS)
    if variant == SMOKE_TEAM:
        raise SystemExit("ERROR: midgame hidden-set fixture did not replace Metagross")
    return variant


TURN_ONE = PublicTurnChoice(
    p1_choice="move psychicfangs +2, move expandingforce +1",
    p2_choice="move psychic +2, move protect",
)
TURN_TWO = PublicTurnChoice(
    p1_choice="move psychicfangs +2, switch 3",
    p2_choice="switch 3, switch 4",
)
PUBLIC_TURNS = (TURN_ONE, TURN_TWO)


def _run(worker, human_team):
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=human_team,
        p2_team=SMOKE_TEAM,
        p1_name="Human",
        p2_name="Practice AI",
        seed=SEED,
    )
    session_id = started["session_id"]
    worker.choose_session(
        session_id, p1_choice=HUMAN_PREVIEW, p2_choice=AI_PREVIEW
    )
    preview_view = worker.session_view(session_id, side="p2")["view"]
    worker.choose_session(
        session_id, p1_choice=TURN_ONE.p1_choice, p2_choice=TURN_ONE.p2_choice
    )
    worker.choose_session(
        session_id, p1_choice=TURN_TWO.p1_choice, p2_choice=TURN_TWO.p2_choice
    )
    midgame_view = worker.session_view(session_id, side="p2")["view"]
    belief = build_public_opponent_belief(midgame_view)
    worlds = materialize_public_belief_worlds(belief, _public_priors(), limit=32)
    reconstructed = reconstruct_midgame_belief_worlds(
        worker,
        battle_format=CHAMPIONS_FORMAT,
        belief=belief,
        worlds=worlds,
        ai_team=SMOKE_TEAM,
        ai_preview=AI_PREVIEW,
        public_turns=PUBLIC_TURNS,
        opponent_side="p1",
        seed=SEED,
    )
    worker.close_session(session_id)
    return preview_view, midgame_view, worlds, reconstructed


def _public_signature(view):
    """Fields exposed by the sanitized player-view schema."""
    return {
        "turn": view["turn"],
        "phase": view["phase"],
        "ended": view["ended"],
        "winner": view["winner"],
        "field": view["field"],
        "request": view["request"],
        "player": view["player"],
        "opponent": view["opponent"],
    }


def main():
    with ShowdownSearchWorker() as worker:
        standard = _run(worker, SMOKE_TEAM)
        variant = _run(worker, _midgame_hidden_variant_team())

    standard_preview, standard_midgame, standard_worlds, standard_reconstructed = standard
    variant_preview, variant_midgame, variant_worlds, variant_reconstructed = variant

    if standard_preview != variant_preview:
        raise SystemExit("ERROR: hidden truth changed the preview public view")
    if standard_worlds != variant_worlds:
        raise SystemExit("ERROR: hidden truth changed materialized worlds")
    if _public_signature(standard_midgame) != _public_signature(variant_midgame):
        raise SystemExit("ERROR: hidden truth changed the controlled public history")
    if len(standard_reconstructed) != len(standard_worlds):
        raise SystemExit("ERROR: reconstruction lost belief worlds")
    if len(variant_reconstructed) != len(variant_worlds):
        raise SystemExit("ERROR: variant reconstruction lost belief worlds")

    if any(world.state.get("turn", 0) < 3 for world in standard_reconstructed):
        raise SystemExit("ERROR: a reconstructed world did not advance through two public turns")

    def mechanics(state):
        return {key: value for key, value in state.items() if key != "log"}

    for left, right in zip(
        standard_reconstructed, variant_reconstructed, strict=True
    ):
        if left.world != right.world or mechanics(left.state) != mechanics(right.state):
            raise SystemExit("ERROR: hidden truth changed reconstructed midgame worlds")

    print("Replay-based midgame belief reconstruction")
    print(f"Worlds: {len(standard_reconstructed)}")
    print(f"Public turn after replay: {standard_reconstructed[0].state.get('turn')}")
    print("History: identical team preview + two resolved public turns")
    print("Stateful history: Protect, damage, opponent switch, AI double switch, terrain")
    print("Anti-cheat: alternate real hidden Metagross set reconstructed identical worlds")
    print("RESULT: belief worlds now preserve public battle history through stateful midgame transitions")


if __name__ == "__main__":
    main()
