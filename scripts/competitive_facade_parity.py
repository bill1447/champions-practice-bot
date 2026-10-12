"""Cross-check evaluation decisions against the actual sealed production facade."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from champions_practice.agent_v2 import PublicCatalog, decide, observe
from champions_practice.belief_controller import SealedBattleFacade
from champions_practice.competitive_evaluation import ROOT, fixtures
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import public_observation_signature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.report.read_text(encoding="utf-8"))
    game = next(g for g in reference["games"] if g["agents"] == {"p1": "v2", "p2": "production"})
    priors, teams = fixtures()
    metadata = PublicCatalog.load(ROOT)
    rows = []
    with SealedBattleFacade(project_root=ROOT, battle_format=CHAMPIONS_FORMAT,
            ai_team=teams[game["teams"]["p2"]], ai_preview_choice="team 1234", opponent_priors=priors,
            decision_budget_seconds=reference["budget_seconds"], conditioning_budget_seconds=reference["budget_seconds"],
            particle_seed=53101, worker_startup_timeout_seconds=30) as battle:
        battle.start(opponent_team=teams[game["teams"]["p1"]], p1_name="P1", p2_name="P2", session_seed=game["battle_seed"])
        battle.commit_preview(human_choice="team 1234")
        for expected in game["rows"]:
            view = battle.public_state()
            assert public_observation_signature(view) == public_observation_signature(expected["sides"]["p1"]["view"])
            own = battle.diagnostic_ai_public_checkpoint()
            assert public_observation_signature(own) == public_observation_signature(expected["sides"]["p2"]["view"])
            legal = battle.legal_human_choices()
            v2 = decide(observe(view, legal, deadline=perf_counter() + reference["budget_seconds"]), metadata)
            ready = battle.lock_ai_action()
            result = battle.commit_human_action(token=ready.token, human_choice=v2.action)
            assert v2.action == expected["sides"]["p1"]["action"]
            assert result.decision.choice == expected["sides"]["p2"]["action"]
            assert result.decision.mode == expected["sides"]["p2"]["telemetry"]["mode"]
            rows.append({"checkpoint": expected["checkpoint"], "v2_action": v2.action,
                         "production_action": result.decision.choice, "mode": result.decision.mode})
        final = battle.public_state()
        assert final["ended"] and final["winner"] == game["winner"]
    result = {"case": game["id"], "full_trace_parity": True, "winner": final["winner"], "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
