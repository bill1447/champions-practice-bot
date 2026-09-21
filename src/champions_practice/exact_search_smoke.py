"""Reproduce the turn-four sacrifice and rank it with exact branch search."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.exact_search import search_exact_turn
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"
ATTACK = "move psychic 1, move psychicfangs 1"
SWITCH = "switch 4, move psychicfangs 1"
WOOD_HAMMER = "move woodhammer 1, pass"


def _turn_four_snapshot(worker: ShowdownSearchWorker) -> dict:
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=SMOKE_TEAM,
        p2_team=SMOKE_TEAM,
        p1_name="Heuristic",
        p2_name="Baseline",
        seed=SEED,
    )
    session_id = started["session_id"]

    choices = [
        ("team 1634", "team 3125"),
        (
            "move psychic 2, move steelroller mega 1",
            "move expandingforce mega 1, move psychic 1",
        ),
        ("", "switch 3, pass"),
        (
            "move psychic 1, move psychicfangs 1",
            "move closecombat 1, move psychic 2",
        ),
        ("", "switch 4, pass"),
        (
            "move psychic 1, move steelroller 2",
            "move woodhammer 2, move psychic 1",
        ),
    ]
    for p1_choice, p2_choice in choices:
        worker.choose_session(
            session_id,
            p1_choice=p1_choice,
            p2_choice=p2_choice,
        )

    snapshot = worker.session_snapshot(session_id)
    worker.close_session(session_id)

    if snapshot["summary"]["turn"] != 4:
        raise SystemExit("ERROR: regression fixture did not reach turn four")
    return snapshot["state"]


def main() -> None:
    with ShowdownSearchWorker() as worker:
        state = _turn_four_snapshot(worker)
        result = search_exact_turn(
            worker,
            state=state,
            side="p1",
            choices=[ATTACK, SWITCH],
            opponent_responses=[WOOD_HAMMER],
        )

    if result.chosen.choice != SWITCH:
        raise SystemExit(
            "ERROR: exact search still preferred sacrificing Indeedee on turn four"
        )

    print("Exact one-ply branch search")
    for candidate in result.ranking:
        print(f"Score: {candidate.worst_score:8.1f}  {candidate.choice}")
    print("Chosen: switch Indeedee to Armarouge + Psychic Fangs")
    print("RESULT: exact board value rejects the needless Indeedee sacrifice")


if __name__ == "__main__":
    main()
