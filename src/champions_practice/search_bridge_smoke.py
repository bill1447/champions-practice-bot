"""Exercise the persistent Python -> Node -> Showdown exact-state bridge."""

from __future__ import annotations

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main() -> None:
    with ShowdownSearchWorker() as worker:
        if not worker.ping():
            raise SystemExit("ERROR: Showdown search worker did not answer ping")

        created = worker.request(
            "create",
            format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview="team 1235",
            p2_preview="team 1235",
            seed="sodium,00000001000000020000000300000004",
        )

        if created["summary"]["turn"] != 1:
            raise SystemExit(
                "ERROR: expected turn 1 after team preview, "
                f"got {created['summary']['turn']}"
            )

        state = created["state"]

        branch_a = worker.request(
            "branch",
            state=state,
            p1_choice="move followme, move rockslide",
            p2_choice="move psychic 1, move rockslide",
        )
        branch_b = worker.request(
            "branch",
            state=state,
            p1_choice="move psychic 1, move closecombat 1",
            p2_choice="move psychic 1, move rockslide",
        )

        if branch_a["summary"]["turn"] != 2 or branch_b["summary"]["turn"] != 2:
            raise SystemExit("ERROR: forked branches did not both advance to turn 2")

        if branch_a["state"] == branch_b["state"]:
            raise SystemExit("ERROR: distinct choices produced identical fork states")

        print("Python / Showdown search bridge")
        print(f"Format:   {CHAMPIONS_FORMAT}")
        print("Worker:   persistent JSONL Node process")
        print("Snapshot: created after team preview")
        print("Branch A: Follow Me + Rock Slide")
        print("Branch B: Psychic + Close Combat")
        print(f"A turn:   {branch_a['summary']['turn']}")
        print(f"B turn:   {branch_b['summary']['turn']}")
        print("RESULT:   Python can fork exact Showdown states on demand")


if __name__ == "__main__":
    main()
