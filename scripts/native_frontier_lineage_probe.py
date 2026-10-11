"""Observe the first ancestry loss; no validation verdict enters generation."""

import json
from pathlib import Path

from champions_practice import native_stochastic_audit as audit
from champions_practice.diversity_league import ROSTERS, team_text
from champions_practice.native_stochastic_tracker import NativeStochasticTracker, PROJECT_ROOT
from champions_practice.native_stochastic_validator import continuous_witness_lineages
from champions_practice.persistent_admission_smoke import SEEDS, fixture
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.strength_league import _source_identity


def probe(oracle, chance_validator, *, label, team, opponent, seed, mode, script=()):
    records = []
    instances = []
    original_tracker, original_validate = audit.NativeStochasticTracker, audit.validate_checkpoint

    class ObservedTracker(NativeStochasticTracker):
        def __init__(self):
            super().__init__()
            instances.append(self)

        def initialize(self, **kwargs):
            self.telemetry = super().initialize(**kwargs)
            return self.telemetry

        def advance(self, **kwargs):
            self.telemetry = super().advance(**kwargs)
            return self.telemetry

    def observe_validation(*args, **kwargs):
        result = original_validate(*args, **kwargs)
        inspection = args[2]
        records.append({"particles": [{"lineage": p["lineage"]} for p in inspection["particles"]],
                        "validation": result, "telemetry": instances[-1].telemetry})
        return result

    audit.NativeStochasticTracker, audit.validate_checkpoint = ObservedTracker, observe_validation
    try:
        game = audit.run_game(oracle, chance_validator, label=label, p1_team=team, p2_team=opponent,
            policy="seeded-mixed" if label == "rain" else "attack-first", oracle_seed=seed,
            samples=96, budget_ms=600, generation=mode, script=script)
    finally:
        audit.NativeStochasticTracker, audit.validate_checkpoint = original_tracker, original_validate
    previous = set()
    diagnosis = None
    for checkpoint, record in enumerate(records):
        current = continuous_witness_lineages(previous, record["validation"].get("witness_ancestry", []),
                                             opening=checkpoint == 0)
        if checkpoint and previous and not current:
            prior = records[checkpoint - 1]
            calls = record["telemetry"]["parent_call_counts"]
            correct_parents = [{"lineage": p["lineage"], "native_calls": calls[index]}
                for index, p in enumerate(prior["particles"]) if p["lineage"] in previous]
            diagnosis = {"checkpoint": checkpoint,
                "current_mechanical_witnesses": record["validation"]["mechanical_witnesses"],
                "previous_matching_parents": correct_parents,
                "all_matching_parents_starved": all(p["native_calls"] == 0 for p in correct_parents),
                "current_witness_parent_lineages": [w["parent_lineage"]
                    for w in record["validation"].get("witness_ancestry", [])],
                "scope": "starvation is proven only for zero-call parents; otherwise generation versus dedup remains unresolved"}
            break
        previous = current
    return {"fixture": label, "generation": mode,
            "reference_trace_fingerprint": game["reference_trace_fingerprint"],
            "completed_reference_game": game["completed_reference_game"], "first_ancestry_loss": diagnosis}


def main():
    team, _ = fixture()
    results = []
    with ShowdownSearchWorker() as oracle, ShowdownSearchWorker(
        worker_script=PROJECT_ROOT / "tools/native-stochastic-validator.js"
    ) as validator:
        for mode in ("guided", "frontier"):
            results.append(probe(oracle, validator, label="rain", team=team_text(ROSTERS["rain"]),
                opponent=team_text(ROSTERS["balance"]), seed=SEEDS[0], mode=mode))
            results.append(probe(oracle, validator, label="pivot-queue", team=team, opponent=team,
                seed=SEEDS[1], mode=mode, script=(("team 1234", "team 1234"),
                    ("move partingshot +1, move protect", "move partingshot +1, move protect"))))
    output = Path("runs/native-frontier/lineage-probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"source_identity": _source_identity(PROJECT_ROOT),
        "oracle_verdict_feedback_to_tracker": False, "results": results}, indent=2) + "\n", encoding="utf-8")
    print(output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
