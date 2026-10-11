import json
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.teams import SMOKE_TEAM
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_rebase import _positive_mechanics_rejection

with HypotheticalSearchWorker() as worker:
    root = worker.create_state(battle_format=CHAMPIONS_FORMAT,
        p1_team=SMOKE_TEAM, p2_team=SMOKE_TEAM,
        p1_preview="team 2135", p2_preview="team 2135",
        seed="sodium,00000001000000020000000300000004")
    result = worker.branch_many(state=root, branches=[{
        "p1_choice": "move protect, move followme",
        "p2_choice": "move protect, move followme",
        "include_state": True,
    }])[0]
    state = result["state"]
    previews = {s: ["Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross"] for s in ("p1", "p2")}
    view = worker.state_view(state=state, side="p2", previews=previews)
    report = worker.materialize_present_hypotheses(state=root, current_view=view, limit=4)
    evidence = {"turn": view["turn"], "outcomes": len(report["outcomes"]), "reason": report.get("reason"),
        "live_terrain_duration": state["field"]["terrainState"].get("duration"),
        "live_own_volatiles": state["sides"][1]["pokemon"][0]["volatiles"]}
    if report["outcomes"]:
        candidate = report["outcomes"][0]["state"]
        evidence["candidate_terrain_duration"] = candidate["field"]["terrainState"].get("duration")
        evidence["candidate_own_volatiles"] = candidate["sides"][1]["pokemon"][0]["volatiles"]
        evidence["same_legal_choices"] = worker.legal_choices(state=state, side="p2") == worker.legal_choices(state=candidate, side="p2")
        evidence["python_admission_rejection"] = _positive_mechanics_rejection(
            candidate, worker.state_view(state=candidate, side="p2", previews=previews),
            current_view=view, ledger=PublicConstraintLedger.from_public_view(view),
            legal_live=tuple(worker.legal_choices(state=state, side="p2")),
            hypothetical_legal=worker.legal_choices(state=candidate, side="p2"))
    print(json.dumps(evidence, indent=2))
