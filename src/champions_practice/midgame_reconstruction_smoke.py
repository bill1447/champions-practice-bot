"""Integration smoke for replay-based midgame belief reconstruction."""

from champions_practice.beliefs import build_public_opponent_belief
from champions_practice.belief_smoke import _hidden_variant_team, _public_priors
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
TURN = PublicTurnChoice(
    p1_choice="move psychicfangs +2, move expandingforce +1",
    p2_choice="move psychic +2, move protect",
)


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
        session_id, p1_choice=TURN.p1_choice, p2_choice=TURN.p2_choice
    )
    midgame_view = worker.session_view(session_id, side="p2")["view"]
    # Materialize from the CURRENT public belief, not the preview belief. The resolved
    # turn publicly reveals Psychic Fangs / Expanding Force; worlds lacking those moves
    # are no longer possible and cannot legally replay the observed history.
    belief = build_public_opponent_belief(midgame_view)
    worlds = materialize_public_belief_worlds(belief, _public_priors(), limit=32)
    reconstructed = reconstruct_midgame_belief_worlds(
        worker,
        battle_format=CHAMPIONS_FORMAT,
        belief=belief,
        worlds=worlds,
        ai_team=SMOKE_TEAM,
        ai_preview=AI_PREVIEW,
        public_turns=(TURN,),
        opponent_side="p1",
        seed=SEED,
    )
    worker.close_session(session_id)
    return preview_view, midgame_view, worlds, reconstructed


def _public_signature(view):
    return {
        "turn": view["turn"],
        "request_state": view["request_state"],
        "field": view["field"],
        "p1": view["p1"],
        "p2": view["p2"],
    }


def main():
    with ShowdownSearchWorker() as worker:
        standard = _run(worker, SMOKE_TEAM)
        variant = _run(worker, _hidden_variant_team())

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

    # Exact reconstructed states should all have advanced beyond the preview position.
    if any(world.state.get("turn", 0) < 2 for world in standard_reconstructed):
        raise SystemExit("ERROR: a reconstructed world did not advance through turn one")

    # Hidden truth must not alter the reconstructed hypotheses themselves. Ignore retained
    # battle-log timestamps by comparing mechanics-bearing top-level state except log.
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
    print("History: identical team preview + one resolved public turn")
    print("Anti-cheat: alternate real hidden Metagross set reconstructed identical worlds")
    print("RESULT: belief worlds now preserve public battle history into the next turn")


if __name__ == "__main__":
    main()
