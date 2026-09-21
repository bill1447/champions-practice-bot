"""Exercise exact legal-action enumeration for persistent sessions."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"


def _assert_private_view_stays_private(view: dict) -> None:
    for active in view["opponent"]["active"]:
        if active is None:
            continue
        leaked = {"item", "ability", "moves"}.intersection(active)
        if leaked:
            raise SystemExit(f"ERROR: public view leaked fields: {sorted(leaked)}")


def main() -> None:
    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_name="Human",
            p2_name="AI",
            seed=SEED,
        )
        session_id = started["session_id"]

        p1_preview = worker.session_legal_choices(session_id, side="p1")
        p2_preview = worker.session_legal_choices(session_id, side="p2")
        if len(p1_preview) != 180 or len(p2_preview) != 180:
            raise SystemExit(
                "ERROR: expected 180 ordered-lead preview choices per side"
            )

        worker.choose_session(
            session_id,
            p1_choice="team 1634",
            p2_choice="team 3125",
        )
        p1_moves = worker.session_legal_choices(session_id, side="p1")
        p2_moves = worker.session_legal_choices(session_id, side="p2")

        expected_p1 = {
            "move followme, move psychicfangs +1 mega",
            "move psychic +2, move steelroller +1 mega",
            "switch 3, switch 4",
        }
        missing = expected_p1.difference(p1_moves)
        if missing:
            raise SystemExit(f"ERROR: missing expected p1 choices: {sorted(missing)}")
        if "switch 3, switch 3" in p1_moves:
            raise SystemExit("ERROR: duplicate joint switch was accepted")
        if any(choice.count(" mega") > 1 for choice in p1_moves + p2_moves):
            raise SystemExit("ERROR: illegal double-Mega choice was accepted")

        snapshot = worker.session_snapshot(session_id)
        if worker.legal_choices(state=snapshot["state"], side="p1") != p1_moves:
            raise SystemExit("ERROR: snapshot and live-session choices diverged")

        _assert_private_view_stays_private(worker.session_view(session_id)["view"])

        worker.choose_session(
            session_id,
            p1_choice="move psychic 2, move steelroller mega 1",
            p2_choice="move expandingforce mega 1, move psychic 1",
        )
        if worker.session_legal_choices(session_id, side="p1") != [""]:
            raise SystemExit("ERROR: waiting side received actionable choices")
        if worker.session_legal_choices(session_id, side="p2") != [
            "switch 3, pass",
            "switch 4, pass",
        ]:
            raise SystemExit("ERROR: forced-switch choices were enumerated incorrectly")

        worker.close_session(session_id)

        print("Persistent-session legal action enumeration")
        print(f"Preview choices: {len(p1_preview)} per side")
        print(f"Turn-one choices: p1={len(p1_moves)} p2={len(p2_moves)}")
        print("Validated: targets, switches, Mega, forced passes, snapshot parity")
        print("Privacy: opponent private set remains absent from player view")
        print("RESULT: exact search can now request its own legal action lists")


if __name__ == "__main__":
    main()
