"""Exercise persistent battle sessions and exact fork parity."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

SEED = "sodium,00000001000000020000000300000004"


def _assert_public_view(view: dict) -> None:
    opponent = view["opponent"]
    if "team" in opponent:
        raise SystemExit("ERROR: player view exposed opponent private team data")

    for active in opponent["active"]:
        if active is None:
            continue
        forbidden = {"item", "ability", "moves"}
        leaked = forbidden.intersection(active)
        if leaked:
            raise SystemExit(
                f"ERROR: player view leaked opponent private fields: {sorted(leaked)}"
            )

    if len(opponent["preview_species"]) != 6:
        raise SystemExit("ERROR: player view leaked the opponent's selected four")

    allowed_reveals = {"species", "moves", "items", "abilities", "fainted", "seen"}
    for observation in opponent["revealed"]:
        unexpected = set(observation).difference(allowed_reveals)
        if unexpected:
            raise SystemExit(
                "ERROR: revealed observation contains private fields: "
                f"{sorted(unexpected)}"
            )


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
        view = started["view"]

        if view["phase"] != "teampreview":
            raise SystemExit(
                f"ERROR: expected teampreview phase, got {view['phase']!r}"
            )
        _assert_public_view(view)

        preview = worker.choose_session(
            session_id,
            p1_choice="team 1235",
            p2_choice="team 1235",
        )["view"]

        if preview["turn"] != 1 or preview["phase"] != "move":
            raise SystemExit(
                "ERROR: session did not advance from team preview to turn 1 move phase"
            )
        _assert_public_view(preview)

        ai_view = worker.session_view(session_id, side="p2")["view"]
        _assert_public_view(ai_view)
        if ai_view["player"]["name"] != "AI" or ai_view["opponent"]["name"] != "Human":
            raise SystemExit("ERROR: p2 sanitized view did not swap player/opponent sides")

        before = worker.session_snapshot(session_id)

        branch = worker.request(
            "branch",
            state=before["state"],
            p1_choice="move followme, move rockslide",
            p2_choice="move psychic 1, move rockslide",
        )

        worker.choose_session(
            session_id,
            p1_choice="move followme, move rockslide",
            p2_choice="move psychic 1, move rockslide",
        )
        after = worker.session_snapshot(session_id)

        if after["summary"] != branch["summary"]:
            raise SystemExit(
                "ERROR: live session resolution diverged from exact fork resolution"
            )

        current_view = worker.session_view(session_id)["view"]
        _assert_public_view(current_view)

        worker.close_session(session_id)

        print("Persistent battle session API")
        print(f"Format:  {CHAMPIONS_FORMAT}")
        print("Preview: human and AI choices accepted independently")
        print("Privacy: private set absent; p1 and p2 sanitized views both work")
        print("Parity:  session turn matches exact fork from same snapshot")
        print("RESULT:  backend is ready to drive a local practice UI")


if __name__ == "__main__":
    main()
