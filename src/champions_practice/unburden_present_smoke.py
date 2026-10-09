"""Pinned Showdown midgame Unburden switch lifecycle regression."""

from __future__ import annotations

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.belief_worlds import PublicSetCandidate
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_rebase import build_present_rebase
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM

OPPONENT_TEAM = """Gengar
Ability: Cursed Body
Level: 50
- Protect

Mimikyu
Ability: Disguise
Level: 50
- Protect

Froslass
Ability: Snow Cloak
Level: 50
- Protect

Chandelure
Ability: Flash Fire
Level: 50
- Protect
"""
P1_PREVIEW = "team 1234"
P2_PREVIEW = "team 2135"
PROTECT = "move protect, move protect"
OWN_STAY = "move protect, move followme"
OWN_SWITCH = "switch 3, move followme"
SEED = "sodium,00000001000000020000000300000004"


def catalog():
    species = [
        ("Gengar", "Cursed Body"),
        ("Mimikyu", "Disguise"),
        ("Froslass", "Snow Cloak"),
        ("Chandelure", "Flash Fire"),
    ]
    return {
        name: (PublicSetCandidate(
            species=name, item=None, ability=ability,
            nature="Serious", stat_points=(), moves=("Protect",),
        ),)
        for name, ability in species
    }


def case(worker, switched):
    start = worker.start_session(
        battle_format=CHAMPIONS_FORMAT, p1_team=OPPONENT_TEAM,
        p2_team=SMOKE_TEAM, p1_name="Public Opponent",
        p2_name="Practice AI", seed=SEED,
    )
    sid = start["session_id"]
    try:
        worker.choose_session(sid, p1_choice=P1_PREVIEW, p2_choice=P2_PREVIEW)

        def advance(own_choice):
            if PROTECT not in worker.session_legal_choices(sid, side="p1"):
                raise SystemExit("ERROR: opponent Protect unavailable")
            legal = worker.session_legal_choices(sid, side="p2")
            if own_choice not in legal:
                raise SystemExit(f"ERROR: own switch not legal: {own_choice}, {legal[:10]}")
            worker.choose_session(sid, p1_choice=PROTECT, p2_choice=own_choice)

        advance(OWN_STAY)
        first = worker.session_view(sid, side="p2")["view"]["player"]["active_details"][0]
        if first["species"] != "Sneasler" or first["item"] is not None:
            raise SystemExit("ERROR: Sneasler did not consume Psychic Seed")
        advance(OWN_SWITCH if switched else OWN_STAY)
        advance(OWN_SWITCH if switched else OWN_STAY)
        view = worker.session_view(sid, side="p2")["view"]
        now = view["player"]["active_details"][0]
        if view["phase"] != "move" or view["turn"] < 4 or now["species"] != "Sneasler":
            raise SystemExit("ERROR: missing midgame Sneasler")
        if switched and not now["speed"] < first["speed"]:
            raise SystemExit("ERROR: switching did not clear live Unburden")
        if not switched and now["speed"] != first["speed"]:
            raise SystemExit("ERROR: retained Unburden speed changed")

        ledger = PublicConstraintLedger.from_public_view(view)
        legal = tuple(worker.session_legal_choices(sid, side="p2"))
        report = build_present_rebase(
            worker, ledger=ledger, current_view=view, priors=catalog(),
            battle_format=CHAMPIONS_FORMAT,
            ai_team=_pin_known_team_genders(SMOKE_TEAM, view["request"]),
            ai_preview_choice=P2_PREVIEW, legal_live=legal,
            max_roots=2, max_particles=4,
        )
        if not report.particles:
            raise SystemExit(
                f"ERROR: current-world Unburden mismatch: {report.unresolved_reason}; "
                f"{report.rejection_reasons}"
            )
        for particle in report.particles:
            own_native = particle.state["sides"][1]["pokemon"][0]
            has_volatile = "unburden" in own_native.get("volatiles", {})
            if has_volatile == switched or own_native["speed"] != now["speed"]:
                raise SystemExit("ERROR: incorrect native speed or Unburden volatile")
            projection = worker.state_view(
                state=particle.state, side="p2",
                previews={
                    "p1": list(ledger.preview_species),
                    "p2": [m["species"] for m in view["player"]["team"]],
                },
            )
            if projection["player"] != view["player"] or projection["request"] != view["request"]:
                raise SystemExit("ERROR: exact own current mechanics lost")
            if set(worker.legal_choices(state=particle.state, side="p2")) != set(legal):
                raise SystemExit("ERROR: own legal moves changed")
        print(f"Unburden switch={switched}: speed {first['speed']} -> {now['speed']}; "
              f"admitted {len(report.particles)}")
        return first["speed"], now["speed"]
    finally:
        worker.close_session(sid)


def main():
    with ShowdownSearchWorker() as worker:
        control = case(worker, False)
        switched = case(worker, True)
    if control[0] != switched[0] or control[1] <= switched[1]:
        raise SystemExit("ERROR: control and switched speeds were not distinct")
    print("RESULT: both native Unburden lifecycles admitted with exact own speed")


if __name__ == "__main__":
    main()
