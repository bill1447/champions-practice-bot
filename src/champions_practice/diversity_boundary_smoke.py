"""Native regressions discovered by the expanded team/policy matrix."""

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import ROSTERS, team_text
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


def main():
    with ShowdownSearchWorker() as worker:
        root = worker.create_state(battle_format=CHAMPIONS_FORMAT,
            p1_team=team_text(ROSTERS["balance"]), p2_team=SMOKE_TEAM,
            p1_preview="team 1234", p2_preview="team 2135",
            seed="sodium,00000001000000020000000300000004")
        previews = {"p1": list(ROSTERS["balance"]), "p2": ["Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross"]}
        view = worker.state_view(state=root, side="p2", previews=previews)
        incineroar = next(mon for mon in view["opponent"]["revealed"] if mon["species"] == "Incineroar")
        assert incineroar["abilities"] == ["intimidate"]
        PublicConstraintLedger.from_public_view(view)
        print('Pinned Intimidate: boost marker excluded; public ledger initialized')

        session = worker.start_session(battle_format=CHAMPIONS_FORMAT,
            p1_team=team_text(ROSTERS["rain"]), p2_team=SMOKE_TEAM,
            seed="sodium,00000001000000020000000300000004")
        sid = session["session_id"]
        try:
            worker.choose_session(sid, p1_choice="team 2341", p2_choice="team 2135")
            worker.choose_session(sid, p1_choice="move electroshot +2, move protect",
                                  p2_choice="move protect, move followme")
            request = worker.session_view(sid, side="p1")["view"]["request"]
            locked = request["active"][0]["moves"]
            assert len(locked) == 1 and locked[0]["id"] == "electroshot" and "target" not in locked[0]
            choices = worker.session_public_choices(sid, side="p1")
            assert choices and all(not choice.startswith("move electroshot,") for choice in choices)
            choice = next(choice for choice in choices if choice.startswith("move electroshot +2, move protect"))
            worker.choose_session(sid, p1_choice=choice, p2_choice="move protect, move followme")
            print('Pinned charging Electro Shot: public explicit-target choice accepted natively')
        finally:
            worker.close_session(sid)


if __name__ == "__main__":
    main()
