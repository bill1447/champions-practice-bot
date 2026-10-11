"""Audit saved public checkpoints independently of a sealed live battle."""

import argparse
import json
from collections import Counter
from pathlib import Path

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.demo_fixture import DEMO_AI_TEAM, DEMO_AI_PREVIEW_CHOICE, demo_public_priors
from champions_practice.diversity_league import audit_report
from champions_practice.present_mechanics import unsupported_present_mechanics
from champions_practice.present_rebase import build_present_rebase
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.strength_league import _atomic_write_json, _source_identity
from champions_practice.uncertain_fixture import FIXTURE_ID, public_priors


def audit_native(report, root):
    checks = []
    counts = Counter()
    with HypotheticalSearchWorker(root) as worker:
        for game in report["games"]:
            ledger = None
            for trace in game["decision_trace"]:
                view = trace["bot_public_before"]
                ledger = PublicConstraintLedger.from_public_view(view) if ledger is None else ledger.advance(view)
                if trace["mode"] != "forced-wait" and view["turn"] >= 2:
                    issue = unsupported_present_mechanics(view, ledger)
                    result = None
                    if issue is None:
                        result = build_present_rebase(worker, ledger=ledger, current_view=view,
                            priors=public_priors() if report["fixture_id"] == FIXTURE_ID else demo_public_priors(),
                            battle_format=report["format_id"],
                            ai_team=_pin_known_team_genders(DEMO_AI_TEAM, view["request"]),
                            ai_preview_choice=DEMO_AI_PREVIEW_CHOICE,
                            legal_live=tuple(trace["ai_public_choices_before"]), max_roots=2, max_particles=4)
                    check = {"game_index": game["game_index"], "decision_index": trace["decision_index"],
                             "turn": view["turn"], "phase": view["phase"], "support_gate": issue,
                             "admitted": bool(result and result.particles)}
                    if result:
                        check.update(roots_tried=result.roots_tried, native_candidates=result.native_candidates,
                            positive_matches=result.positive_matches, admitted_particles=len(result.particles),
                            rejection_reasons=dict(result.rejection_reasons), unresolved_reason=result.unresolved_reason,
                            historical_witnesses=result.historical_witnesses,
                            exhaustively_excluded_worlds=result.exhaustively_excluded_worlds)
                    counts["checked"] += 1
                    counts["admitted" if check["admitted"] else "unresolved"] += 1
                    checks.append(check)
                ledger = ledger.advance(trace["bot_public_after"])
    return {"authority": "independent-offline-public-checkpoint-reconstruction",
            "counts": dict(counts), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = _source_identity(root)
    for path in args.reports:
        report = json.loads(path.read_text())
        audit = {"trace_audit": audit_report(report), "audit_source": source,
                 "original_source": report["source_identity"], "native_audit": audit_native(report, root)}
        output = root / "runs" / "admission-audit" / report["run_id"] / "report.json"
        _atomic_write_json(output, audit)
        print(report["run_id"], audit["trace_audit"], audit["native_audit"]["counts"], flush=True)
    if _source_identity(root) != source:
        raise RuntimeError("source changed during admission audit")


if __name__ == "__main__":
    main()
