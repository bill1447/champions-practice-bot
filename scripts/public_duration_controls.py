"""Native public weather admission controls; oracle counters used only in assertions."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog
from champions_practice.persistent_admission_smoke import fixture, advance, SEEDS
from champions_practice.present_mechanics import public_weather_plan
from champions_practice.present_rebase import build_present_rebase, _positive_mechanics_rejection
from champions_practice.search_worker import ShowdownSearchWorker


def main():
    results = []
    with ShowdownSearchWorker(startup_timeout_seconds=60) as worker:
        for weather, setter in (("raindance", "Pelipper"), ("sandstorm", "Tyranitar")):
            own, priors = fixture()
            member = replace(catalog()[setter][0], moves=(("Protect", "Hurricane", "Hydro Pump", "Weather Ball") if setter == "Pelipper" else catalog()[setter][0].moves), item="")
            priors["Dragonite"] = (replace(priors["Dragonite"][0], moves=("Protect", "Dragon Claw", "Extreme Speed", "Rock Slide")),)
            own = own.replace("High Horsepower", "Rock Slide")
            extras = "\n\n".join(catalog()[name][0].team_text for name in ("Rillaboom", "Venusaur"))
            own += "\n\n" + extras
            names = (setter, "Dragonite", "Metagross", "Rotom-Wash", "Rillaboom", "Venusaur")
            priors = {name: priors[name] for name in names if name in priors}
            rock = "Damp Rock" if weather == "raindance" else "Smooth Rock"
            priors[setter] = (member, replace(member, item=rock))
            for extra in ("Rillaboom", "Venusaur"):
                priors[extra] = (catalog()[extra][0],)
            foe = "\n\n".join(priors[name][0].team_text for name in names)
            for item in ("", rock):
                checked_team = foe.replace(setter+"\n", setter+(" @ "+item if item else "")+"\n", 1)
                assert not item or ("@ "+item) in checked_team
                validation = worker.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=checked_team)
                assert validation["valid"], validation["problems"]
            own_validation = worker.validate_team(battle_format=CHAMPIONS_FORMAT, team_text=own)
            assert own_validation["valid"], own_validation["problems"]
            previews = {"p1": list(names), "p2": ["Incineroar", "Dragonite", "Metagross", "Rotom-Wash", "Rillaboom", "Venusaur"]}
            root = worker.create_state(battle_format=CHAMPIONS_FORMAT, p1_team=foe, p2_team=own,
                p1_preview="team 1234", p2_preview="team 1234", seed=SEEDS[0])
            initial = worker.state_view(state=root, side="p2", previews=previews)
            ledger = PublicConstraintLedger.from_public_view(initial)
            current, ledger, view = advance(worker, root, ledger, previews,
                "move protect, move protect", "move protect, move protect")
            assert public_weather_plan(view, ledger) == {"weather": weather, "residual_turns": 1}
            legal = tuple(worker.legal_choices(state=current, side="p2"))
            reports = []
            for source_prior in priors[setter]:
                bounded_priors = {**priors, setter: (source_prior,)}
                report = build_present_rebase(worker, ledger=ledger, current_view=view, priors=bounded_priors,
                battle_format=CHAMPIONS_FORMAT, ai_team=_pin_known_team_genders(own, view["request"]),
                ai_preview_choice="team 1234", legal_live=legal, max_roots=4, max_particles=8)
                assert report.particles, (weather, report.unresolved_reason, report.rejection_reasons)
                for particle in report.particles:
                    state = particle.state
                    assert current["field"]["weatherState"]["duration"] == 4
                    assert state["field"]["weatherState"]["duration"] == (7 if source_prior.item else 4)
                    projected = worker.state_view(state=state, side="p2", previews=previews)
                    assert _positive_mechanics_rejection(state, projected, current_view=view, ledger=ledger,
                        legal_live=legal, hypothetical_legal=worker.legal_choices(state=state, side="p2")) is None
                    corrupted = deepcopy(state)
                    corrupted["field"]["weatherState"]["duration"] += 1
                    assert _positive_mechanics_rejection(corrupted, projected, current_view=view, ledger=ledger,
                        legal_live=legal, hypothetical_legal=worker.legal_choices(state=state, side="p2")) == "unsupported-persistent:field-duration-mismatch"
                reports.append(report)
            assert {p.state["field"]["weatherState"]["duration"] for r in reports for p in r.particles} == {4, 7}
            results.append({"weather": weather, "particles_per_item_domain": [len(r.particles) for r in reports], "native_remaining_hypotheses": [4, 7], "both_source_item_teams_legal": True,
                "public_projection_and_legal_menu_match": True, "corrupted_timer_rejected": True})
            print(weather, len(report.particles), "validated", flush=True)
    output = Path("runs/v2-public-durations/native-controls.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2)+"\n")


if __name__ == "__main__":
    main()

