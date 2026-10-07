"""Pinned-Showdown smoke for public Mega-command reconstruction."""

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
ORDINARY = "move protect, move followme"
MEGA = "move protect mega, move followme"


def _require_choice(choices: tuple[str, ...], choice: str) -> str:
    if choice not in choices:
        raise SystemExit(
            f"ERROR: expected pinned Champions command {choice!r} was not legal"
        )
    return choice


def _mega_events(view: dict) -> list[list[str]]:
    delta = view.get("public_event_delta")
    if not isinstance(delta, dict):
        return []
    events = delta.get("events")
    if not isinstance(events, list):
        return []
    return [
        event
        for event in events
        if isinstance(event, list) and event and event[0] == "-mega"
    ]


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            seed="sodium,16716716716716716716716716716716",
        )
        before = worker.state_view(
            state=state,
            side="p2",
            previews=PREVIEWS,
        )
        p1_legal = tuple(worker.legal_choices(state=state, side="p1"))
        p2_legal = tuple(worker.legal_choices(state=state, side="p2"))

        ordinary = _require_choice(p1_legal, ORDINARY)
        mega = _require_choice(p1_legal, MEGA)
        p2_choice = _require_choice(p2_legal, ORDINARY)

        results = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": ordinary,
                    "p2_choice": p2_choice,
                    "include_state": True,
                    "view_side": "p2",
                    "rng_seed": "sodium,0123456789abcdef0123456789abcdef",
                    "previews": PREVIEWS,
                },
                {
                    "p1_choice": mega,
                    "p2_choice": p2_choice,
                    "include_state": True,
                    "view_side": "p2",
                    "rng_seed": "sodium,0123456789abcdef0123456789abcdef",
                    "previews": PREVIEWS,
                },
            ],
        )
        ordinary_view = results[0]["view"]
        mega_view = results[1]["view"]

        if _mega_events(ordinary_view):
            raise SystemExit(
                "ERROR: ordinary Gardevoir command emitted public Mega evidence"
            )
        mega_events = _mega_events(mega_view)
        if len(mega_events) != 1 or mega_events[0][1:4] != [
            "p1a",
            "gardevoir",
            "gardevoirite",
        ]:
            raise SystemExit(
                "ERROR: pinned Champions -mega event shape changed: "
                f"{mega_events!r}"
            )

        ordinary_candidates = observed_joint_move_candidates(
            ordinary_view,
            previous_public_view=before,
        )
        if ordinary_candidates != (ordinary,):
            raise SystemExit(
                "ERROR: no-Mega public trace reconstructed transformation "
                f"commands: {ordinary_candidates!r}"
            )

        mega_candidates = observed_joint_move_candidates(
            mega_view,
            previous_public_view=before,
        )
        if ordinary in mega_candidates:
            raise SystemExit(
                "ERROR: public Mega trace still reconstructed an ordinary command"
            )
        resolved_mega = tuple(
            worker.validate_choices(
                state=state,
                side="p1",
                candidates=list(mega_candidates),
            )
        )
        if resolved_mega != (mega,):
            raise SystemExit(
                "ERROR: public Mega family did not resolve to the exact pinned "
                f"Champions command: {resolved_mega!r}"
            )

        print("Public transformation command reconstruction")
        print(f"Ordinary command: {ordinary}")
        print(f"Mega command:     {mega}")
        print(f"Pinned -mega:     {mega_events[0]}")
        print(f"Mega candidates:  {mega_candidates}")
        print(
            "RESULT: public -mega evidence constrains transformation modifiers, "
            "while an aligned no-Mega trace excludes them"
        )


if __name__ == "__main__":
    main()
