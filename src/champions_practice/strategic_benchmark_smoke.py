"""Real-Showdown executable strategic benchmark smoke."""

from __future__ import annotations

from types import SimpleNamespace

from champions_practice.belief_search import ExactBeliefWorldState
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.strategic_benchmarks import (
    STRATEGIC_BENCHMARKS,
    StrategicBenchmarkSuite,
    format_strategic_benchmark_report,
    run_generated_strategy_benchmark,
)
from champions_practice.strategy_evidence import format_strategic_plan_probe

AI_TEAM = """Indeedee-F @ Colbur Berry
Ability: Psychic Surge
Level: 50
EVs: 32 HP / 32 Def / 2 Spe
Relaxed Nature
- Psychic
- Follow Me
- Trick Room
- Protect

Sneasler @ Psychic Seed
Ability: Unburden
Level: 50
EVs: 2 HP / 32 Atk / 32 Spe
Adamant Nature
- Close Combat
- Dire Claw
- Rock Slide
- Protect

Alakazam @ Focus Sash
Ability: Synchronize
Level: 50
EVs: 2 HP / 32 SpA / 32 Spe
Timid Nature
- Psychic
- Protect

Gengar @ Life Orb
Ability: Cursed Body
Level: 50
EVs: 2 HP / 32 SpA / 32 Spe
Timid Nature
- Shadow Ball
- Protect
"""

OPPONENT_TEAM = """Lucario @ Sitrus Berry
Ability: Inner Focus
Level: 50
EVs: 32 HP / 32 Atk / 2 Spe
Adamant Nature
- Swords Dance

Arcanine @ Leftovers
Ability: Intimidate
Level: 50
EVs: 32 HP / 32 Atk / 2 Spe
Adamant Nature
- Howl

Rotom-Wash @ Wiki Berry
Ability: Levitate
Level: 50
EVs: 32 HP / 32 SpA / 2 Spe
Modest Nature
- Nasty Plot

Kommo-o @ Lum Berry
Ability: Bulletproof
Level: 50
EVs: 32 HP / 32 Def / 2 Spe
Impish Nature
- Iron Defense
"""

PREVIEW = "team 1234"
SEED = "sodium,99999999000000020000000300000004"
RNG_SEED = (
    "sodium,"
    "abababababababababababababababababababababababababababababababab"
)


def _case():
    return next(
        case
        for case in STRATEGIC_BENCHMARKS
        if case.case_id == "sneasler-neutral-trick-room-showdown"
    )


def main() -> None:
    with ShowdownSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=AI_TEAM,
            p2_team=OPPONENT_TEAM,
            p1_preview=PREVIEW,
            p2_preview=PREVIEW,
            p1_name="Benchmark AI",
            p2_name="Benchmark Opponent",
            seed=SEED,
        )
        view = worker.state_view(state=state, side="p1")

        active = [
            pokemon.get("species")
            for pokemon in view["player"]["active_details"]
            if isinstance(pokemon, dict)
        ]
        if active != ["Indeedee-F", "Sneasler"]:
            raise SystemExit(
                "ERROR: strategic benchmark did not start Indeedee-F + Sneasler: "
                f"{active!r}"
            )

        own_profiles = {
            pokemon["species"]: pokemon
            for pokemon in view["player"]["team"]
            if isinstance(pokemon, dict)
        }
        sneasler_profile = own_profiles.get("Sneasler")
        indeedee_profile = own_profiles.get("Indeedee-F")
        if not isinstance(sneasler_profile, dict) or not isinstance(indeedee_profile, dict):
            raise SystemExit("ERROR: own strategic profiles are missing from player view")
        if sneasler_profile.get("damaging_move_count") != 3:
            raise SystemExit(
                "ERROR: Sneasler damaging-move count was not derived from Showdown"
            )
        if indeedee_profile.get("damaging_move_count") != 1:
            raise SystemExit(
                "ERROR: Indeedee-F damaging-move count was not derived from Showdown"
            )
        if not isinstance(sneasler_profile.get("speed"), int):
            raise SystemExit("ERROR: own exact speed is missing from player view")

        legal = worker.legal_choices(state=state, side="p1")
        if not any("move trickroom" in choice for choice in legal):
            raise SystemExit("ERROR: real benchmark state has no legal Trick Room line")
        if not any("move psychic" in choice for choice in legal):
            raise SystemExit("ERROR: real benchmark state has no legal Psychic line")

        execution = run_generated_strategy_benchmark(
            worker,
            case=_case(),
            view=view,
            particles=(SimpleNamespace(weight=1.0, world_id="showdown-world"),),
            worlds=(
                ExactBeliefWorldState(
                    state=state,
                    weight=1.0,
                    label="showdown-world",
                ),
            ),
            side="p1",
            plan_limit=4,
            candidate_limit=4,
            response_limit=2,
            rng_seeds=(
                RNG_SEED,
                "sodium,"
                "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd",
            ),
        )

        probes = {probe.plan.name: probe for probe in execution.probes}
        speed_probe = probes.get("establish-speed-control-indeedeef")
        preserve_probe = probes.get("preserve-indeedeef")
        if speed_probe is None or preserve_probe is None:
            raise SystemExit(
                "ERROR: real strategy generation/probing missed required benchmark plans: "
                f"generated={execution.generated_plan_names!r}; "
                f"probed={execution.probed_plan_names!r}"
            )
        if speed_probe.sampled_robust:
            raise SystemExit(
                "ERROR: neutral Trick Room received sampled-robust strategic authority"
            )
        if not preserve_probe.sampled_robust:
            raise SystemExit(
                "ERROR: preserve-Indeedee plan was not sampled robust in harmless benchmark state"
            )
        if execution.selected_probe is None:
            raise SystemExit("ERROR: executable benchmark selected no supported plan")
        if execution.selected_probe.plan.name != "preserve-indeedeef":
            raise SystemExit(
                "ERROR: real strategy stack selected the wrong plan: "
                f"{execution.selected_probe.plan.name}"
            )
        if execution.result.status != "pass":
            raise SystemExit(
                "ERROR: real strategic benchmark failed: "
                + "; ".join(execution.result.failures)
            )

        print("Executable strategic benchmark")
        print("Public position: Indeedee-F + Sneasler vs mid-speed opponents")
        print("Generated plans: " + ", ".join(execution.generated_plan_names))
        print("Probed plans: " + ", ".join(execution.probed_plan_names))
        print(
            "Selected plan: "
            f"{execution.selected_probe.plan.name} -> "
            f"{execution.selected_probe.chosen.choice}"
        )
        print(f"Exact plan branches: {execution.exact_branch_count}")
        print(
            "Response-screening branches: "
            f"{execution.response_screening_branch_count}"
        )
        print(format_strategic_plan_probe(speed_probe))
        print(format_strategic_plan_probe(preserve_probe))
        print(
            format_strategic_benchmark_report(
                StrategicBenchmarkSuite(results=(execution.result,))
            )
        )
        print("RESULT: real Showdown state passes labeled strategic plan selection")


if __name__ == "__main__":
    main()
