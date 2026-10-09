"""Pinned Showdown midgame: an opposing fainted slot must not erase search.

Public evidence comes ONLY from p2's sanitized session view; the constructor
receives a separate fresh public-prior opening, never the live session state.
Three native Explosion self-KOs leave the opponent with one living active
Pokemon, no reserve, and a fainted occupied slot during a move request.
"""

from __future__ import annotations

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.belief_worlds import PublicSetCandidate
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_rebase import build_present_rebase
from champions_practice.search_worker import FORCED_WAIT_CHOICE, ShowdownSearchWorker
from champions_practice.sealed_transition_smoke import SELF_KO_TEAM

# Ghost leads are immune to opposing Explosion even if repeat Protect fails.
# This makes the three native self-KOs deterministic across PRNG branches.
GHOST_TEAM = """Gengar
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

PREVIEW = "team 1234"
SEED = "sodium,00000001000000020000000300000004"
PROTECT = "move protect, move protect"
DOUBLE_EXPLOSION = "move explosion, move explosion"
THIRD_EXPLOSION = "move explosion, move protect"


def public_priors() -> dict[str, tuple[PublicSetCandidate, ...]]:
    result = {}
    species = (
        ("Indeedee-F", "Synchronize", ("Explosion", "Protect")),
        ("Sneasler", "Unburden", ("Explosion", "Protect")),
        ("Gardevoir", "Trace", ("Explosion", "Protect")),
        ("Armarouge", "Flash Fire", ("Explosion", "Protect")),
    )
    for name, ability, moves in species:
        result[name] = (PublicSetCandidate(
            species=name, item=None, ability=ability,
            nature="Serious", stat_points=(), moves=moves,
        ),)
    return result


def main() -> None:
    with ShowdownSearchWorker() as worker:
        started = worker.start_session(
            battle_format=CHAMPIONS_FORMAT, p1_team=SELF_KO_TEAM,
            p2_team=GHOST_TEAM, p1_name="Human", p2_name="Practice AI",
            seed=SEED,
        )
        sid = started["session_id"]
        try:
            worker.choose_session(sid, p1_choice=PREVIEW, p2_choice=PREVIEW)
            if DOUBLE_EXPLOSION not in worker.session_legal_choices(sid, side="p1"):
                raise SystemExit("ERROR: initial native double Explosion choice missing")
            worker.choose_session(
                sid, p1_choice=DOUBLE_EXPLOSION, p2_choice=PROTECT,
            )
            if FORCED_WAIT_CHOICE not in worker.session_legal_choices(sid, side="p2"):
                raise SystemExit("ERROR: p2 did not wait for opposing replacements")
            choices = worker.session_legal_choices(sid, side="p1")
            replacement = next((x for x in choices if x.count("switch ") == 2), None)
            if replacement is None:
                raise SystemExit("ERROR: native double replacement not offered")
            worker.choose_session(
                sid, p1_choice=replacement, p2_choice=FORCED_WAIT_CHOICE,
            )
            if THIRD_EXPLOSION not in worker.session_legal_choices(sid, side="p1"):
                raise SystemExit("ERROR: third native Explosion choice missing")
            worker.choose_session(
                sid, p1_choice=THIRD_EXPLOSION, p2_choice=PROTECT,
            )
            view = worker.session_view(sid, side="p2")["view"]
            legal = worker.session_legal_choices(sid, side="p2")
            if view["phase"] != "move" or view["ended"] or view["turn"] < 3:
                raise SystemExit(
                    "ERROR: fixture did not reach living move-phase after 3 KOs: "
                    f"{view['phase']} turn {view['turn']}"
                )
            active = view["opponent"]["active"]
            dead = [
                i for i, x in enumerate(active)
                if x is not None and x["fainted"] and x["hp_percent"] == 0
            ]
            alive = [
                i for i, x in enumerate(active)
                if x is not None and not x["fainted"] and x["hp_percent"] > 0
            ]
            if len(dead) != 1 or len(alive) != 1:
                raise SystemExit(
                    "ERROR: pinned public view has no occupied fainted opponent slot: "
                    f"dead={dead} alive={alive}"
                )

            # Full positive public-ledger provenance, no private snapshot or
            # opponent hidden command enters build_present_rebase.
            ledger = PublicConstraintLedger.from_public_view(view)
            # Match the production controller: random gender rolls from a
            # separate fresh Showdown root must not change the known own
            # request.details (e.g. Chandelure's M/F flag).
            pinned_ai_team = _pin_known_team_genders(GHOST_TEAM, view["request"])
            report = build_present_rebase(
                worker, ledger=ledger, current_view=view,
                priors=public_priors(), battle_format=CHAMPIONS_FORMAT,
                ai_team=pinned_ai_team, ai_preview_choice=PREVIEW,
                legal_live=tuple(legal), max_roots=2, max_particles=4,
            )
            if not report.particles:
                raise SystemExit(
                    "ERROR: native fainted-slot public constructor failed: "
                    f"{report.unresolved_reason}; {report.rejection_reasons}"
                )
            for particle in report.particles:
                projection = worker.state_view(
                    state=particle.state, side="p2",
                    previews={
                        "p1": list(ledger.preview_species),
                        "p2": [x["species"] for x in view["player"]["team"]],
                    },
                )
                if projection["request"] != view["request"]:
                    raise SystemExit("ERROR: fainted-slot witness forged own request")
                if projection["opponent"]["active"][dead[0]] is None:
                    raise SystemExit("ERROR: fainted slot disappeared from projection")
                if not projection["opponent"]["active"][dead[0]]["fainted"]:
                    raise SystemExit("ERROR: fainted slot was resurrected")
                if not set(worker.legal_choices(state=particle.state, side="p2")) == set(legal):
                    raise SystemExit("ERROR: fainted-slot witness changed legal moves")
            print("RESULT: native fainted opponent slot admitted for exact search")
            print(f"Current public turn: {view['turn']}")
            print(f"Fainted active slot: {dead[0]}")
            print(f"Admitted native hypotheses: {len(report.particles)}")
            print("Exact own request and legal choices retained: YES")
            print("Live hidden session copied into constructor: NO")
        finally:
            worker.close_session(sid)


if __name__ == "__main__":
    main()
