"""Pinned-runtime regression for exact whole-side forced-wait representation."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import (
    BeliefParticle,
    condition_particles,
    public_observation_signature,
)
from champions_practice.search_worker import (
    FORCED_WAIT_CHOICE,
    ShowdownSearchWorker,
)

PREVIEW = "team 1234"
EXPLODE = "move explosion, move explosion"
PROTECT = "move protect, move protect"

SELF_KO_TEAM = """Indeedee-F
Ability: Synchronize
Level: 50
- Explosion
- Protect

Sneasler
Ability: Unburden
Level: 50
- Explosion
- Protect

Gardevoir
Ability: Trace
Level: 50
- Protect

Armarouge
Ability: Flash Fire
Level: 50
- Protect
"""

WAITING_TEAM = """Indeedee-F
Ability: Synchronize
Level: 50
- Protect

Sneasler
Ability: Unburden
Level: 50
- Protect

Gardevoir
Ability: Trace
Level: 50
- Protect

Armarouge
Ability: Flash Fire
Level: 50
- Protect
"""


def main() -> None:
    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SELF_KO_TEAM,
            p2_team=WAITING_TEAM,
            p1_name="Forced Human",
            p2_name="Waiting AI",
            seed="1,2,3,4",
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
                p1_choice=EXPLODE,
                p2_choice=PROTECT,
            )

            public_wait = worker.session_public_choices(session_id, side="p2")
            exact_wait = worker.session_legal_choices(session_id, side="p2")
            if public_wait != [FORCED_WAIT_CHOICE]:
                raise SystemExit(
                    "ERROR: public wait was not represented explicitly: "
                    f"{public_wait!r}"
                )
            if exact_wait != [FORCED_WAIT_CHOICE]:
                raise SystemExit(
                    "ERROR: exact wait was not represented explicitly: "
                    f"{exact_wait!r}"
                )

            snapshot = worker.session_snapshot(session_id)["state"]
            before = worker.session_view(session_id, side="p2")["view"]

            validated = worker.validate_choices(
                state=snapshot,
                side="p2",
                candidates=[FORCED_WAIT_CHOICE],
            )
            if validated != [FORCED_WAIT_CHOICE]:
                raise SystemExit(
                    "ERROR: exact validator rejected canonical forced wait: "
                    f"{validated!r}"
                )

            try:
                worker.validate_choices(
                    state=snapshot,
                    side="p2",
                    candidates=[""],
                )
            except ValueError:
                pass
            else:
                raise SystemExit(
                    "ERROR: raw empty candidate bypassed the canonical wait token"
                )

            replacements = worker.session_legal_choices(session_id, side="p1")
            replacement = next(
                (
                    choice
                    for choice in replacements
                    if choice.count("switch ") == 2
                ),
                None,
            )
            if replacement is None:
                raise SystemExit(
                    "ERROR: self-KO side did not expose a double replacement"
                )

            branched = worker.branch_many(
                state=snapshot,
                branches=[
                    {
                        "p1_choice": replacement,
                        "p2_choice": FORCED_WAIT_CHOICE,
                        "include_state": True,
                        "view_side": "p2",
                        "previews": previews,
                    }
                ],
            )[0]
            branch_view = branched.get("view")
            if not isinstance(branch_view, dict):
                raise SystemExit("ERROR: forced-wait branch omitted public view")

            try:
                worker.branch_many(
                    state=snapshot,
                    branches=[
                        {
                            "p1_choice": replacement,
                            "p2_choice": "",
                            "include_state": True,
                        }
                    ],
                )
            except ValueError:
                pass
            else:
                raise SystemExit(
                    "ERROR: raw empty branch bypassed the canonical wait token"
                )

            worker.choose_session(
                session_id,
                p1_choice=replacement,
                p2_choice=FORCED_WAIT_CHOICE,
            )
            actual = worker.session_view(session_id, side="p2")["view"]

            if public_observation_signature(branch_view) != public_observation_signature(
                actual
            ):
                raise SystemExit(
                    "ERROR: hypothetical explicit wait diverged from live submission"
                )

            update = condition_particles(
                worker,
                particles=(
                    BeliefParticle(
                        state=snapshot,
                        weight=1.0,
                        world_id="forced-wait",
                        history_id="pre-replacement",
                    ),
                ),
                ai_side="p2",
                ai_choice=FORCED_WAIT_CHOICE,
                actual_public_view=actual,
                previous_public_view=before,
                rng_seeds=(None,),
                previews=previews,
            )
            if not update.particles or update.matched <= 0:
                raise SystemExit(
                    "ERROR: particle conditioning rejected exact forced-wait history"
                )

            try:
                worker.choose_session(
                    session_id,
                    p1_choice=FORCED_WAIT_CHOICE,
                    p2_choice="",
                )
            except ValueError:
                pass
            else:
                raise SystemExit(
                    "ERROR: live session API accepted raw empty choice"
                )

            print("Exact forced-wait authority")
            print(f"Public choice: {public_wait}")
            print(f"Exact choice: {exact_wait}")
            print(f"Replacement paired with: {FORCED_WAIT_CHOICE}")
            print(f"Conditioning matches: {update.matched}")
            print("Raw empty choice accepted: NO")
            print("RESULT: forced wait has one exact non-empty representation")
        finally:
            worker.close_session(session_id)


if __name__ == "__main__":
    main()
