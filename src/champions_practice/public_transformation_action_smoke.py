"""Pinned-runtime smoke for public transformation command evidence."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import observed_joint_move_candidates
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


PREVIEW = "team 3152"
PREVIEWS = {
    "p1": [
        "Indeedee-F",
        "Sneasler",
        "Gardevoir",
        "Armarouge",
        "Rillaboom",
        "Metagross",
    ],
    "p2": [
        "Indeedee-F",
        "Sneasler",
        "Gardevoir",
        "Armarouge",
        "Rillaboom",
        "Metagross",
    ],
}
PLAIN = "move protect, move followme"
MEGA = "move protect mega, move followme"
AI_CHOICE = "move protect, move followme"
RNG_SEED = "sodium,16716716716716716716716716716716"


def _resolve(
    worker: HypotheticalSearchWorker,
    *,
    state: dict,
    p1_choice: str,
) -> dict:
    return worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": p1_choice,
                "p2_choice": AI_CHOICE,
                "include_state": True,
                "view_side": "p2",
                "rng_seed": RNG_SEED,
                "previews": PREVIEWS,
            }
        ],
    )[0]["view"]


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            seed="sodium,11111111222222223333333344444444",
        )
        before = worker.state_view(
            state=state,
            side="p2",
            previews=PREVIEWS,
        )

        legal = set(worker.legal_choices(state=state, side="p1"))
        if PLAIN not in legal or MEGA not in legal:
            raise SystemExit(
                "ERROR: transformation fixture does not expose both plain and "
                f"Mega commands: plain={PLAIN in legal}, mega={MEGA in legal}"
            )

        plain_view = _resolve(worker, state=state, p1_choice=PLAIN)
        mega_view = _resolve(worker, state=state, p1_choice=MEGA)

        plain_candidates = observed_joint_move_candidates(
            plain_view,
            previous_public_view=before,
        )
        mega_candidates = observed_joint_move_candidates(
            mega_view,
            previous_public_view=before,
        )

        if PLAIN not in plain_candidates:
            raise SystemExit(
                "ERROR: plain public turn did not retain the plain command: "
                f"{plain_candidates!r}"
            )
        if any(" mega" in candidate for candidate in plain_candidates):
            raise SystemExit(
                "ERROR: public turn without a Mega event invented a Mega command: "
                f"{plain_candidates!r}"
            )
        if MEGA not in mega_candidates:
            raise SystemExit(
                "ERROR: public Mega event did not retain the Mega command: "
                f"{mega_candidates!r}"
            )
        if PLAIN in mega_candidates:
            raise SystemExit(
                "ERROR: public Mega event still allowed the non-Mega command: "
                f"{mega_candidates!r}"
            )

        print("Public transformation command evidence")
        print(f"Plain candidates: {plain_candidates}")
        print(f"Mega candidates: {mega_candidates}")
        print(
            "RESULT: aligned public Mega evidence selects the exact move modifier "
            "and aligned absence excludes invented Mega commands"
        )


if __name__ == "__main__":
    main()
