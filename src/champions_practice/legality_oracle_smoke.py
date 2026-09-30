"""Regression for hidden-state pre-seal legality leakage."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.search_worker import ShowdownSearchWorker

SEED = "sodium,00000001000000020000000300000004"
PREVIEW = "team 1234"

HUMAN_TEMPLATE = """Gothitelle
Ability: {ability}
Level: 50
- Protect

Indeedee-F
Ability: Synchronize
Level: 50
- Protect

Rillaboom
Ability: Overgrow
Level: 50
- Protect

Sneasler
Ability: Unburden
Level: 50
- Protect
"""

AI_TEAM = """Gengar
Ability: Cursed Body
Level: 50
- Protect

Armarouge
Ability: Flash Fire
Level: 50
- Protect

Rillaboom
Ability: Overgrow
Level: 50
- Protect

Sneasler
Ability: Unburden
Level: 50
- Protect
"""


def _case(
    worker: ShowdownSearchWorker,
    ability: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=HUMAN_TEMPLATE.format(ability=ability),
        p2_team=AI_TEAM,
        p1_name="Human",
        p2_name="AI",
        seed=SEED,
    )
    session_id = started["session_id"]
    try:
        worker.choose_session(
            session_id,
            p1_choice=PREVIEW,
            p2_choice=PREVIEW,
        )
        view = worker.session_view(session_id, side="p2")["view"]
        signature = public_observation_signature(view)
        exact = tuple(worker.session_legal_choices(session_id, side="p2"))
        public = tuple(worker.session_public_choices(session_id, side="p2"))
        return signature, exact, public
    finally:
        worker.close_session(session_id)


def main() -> None:
    with ShowdownSearchWorker() as worker:
        shadow_signature, shadow_exact, shadow_public = _case(worker, "Shadow Tag")
        competitive_signature, competitive_exact, competitive_public = _case(
            worker,
            "Competitive",
        )

    if shadow_signature != competitive_signature:
        raise SystemExit(
            "ERROR: hidden-ability fixture did not produce identical public views"
        )
    if shadow_exact == competitive_exact:
        raise SystemExit(
            "ERROR: fixture did not reproduce hidden-state exact legality difference"
        )
    if shadow_public != competitive_public:
        raise SystemExit(
            "ERROR: public pre-seal choices still depend on hidden opponent ability"
        )
    if not shadow_public:
        raise SystemExit("ERROR: public pre-seal choice set is empty")

    print("Hidden legality oracle regression")
    print(
        "Exact choices: "
        f"Shadow Tag={len(shadow_exact)} Competitive={len(competitive_exact)}"
    )
    print(f"Public pre-seal choices: {len(shadow_public)} in both states")
    print("RESULT: identical public states expose identical AI pre-seal choices")


if __name__ == "__main__":
    main()
