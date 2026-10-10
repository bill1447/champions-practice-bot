"""Pinned Showdown midgame Unburden switch lifecycle regression."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.belief_worlds import PublicSetCandidate
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.present_rebase import build_present_rebase
from champions_practice.search_worker import (
    OwnSpeedDiagnosticTransportError,
    ShowdownSearchWorker,
)
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
        # Offline provenance oracle ONLY: the public own_speed observation
        # is exactly the pinned live Pokemon.speed cached field. The full
        # sealed session snapshot is NEVER given to the fresh constructor.
        snapshot = worker.request("session_snapshot", session_id=sid)
        own_native = snapshot["state"]["sides"][1]["pokemon"][0]
        if (
            type(now["speed"]) is not int
            or now["speed"] != own_native["speed"]
            or view["player"]["team"][0]["speed"] != own_native["speed"]
        ):
            raise SystemExit(
                "ERROR: own observed Speed did not originate at native Pokemon.speed"
            )
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
        if switched:
            # Diagnostic-only negative control. Changing our observed speed
            # makes this view intentionally impossible: it must be rejected,
            # never used as a search world, and must return only own data.
            corrupted = deepcopy(view)
            impossible = now["speed"] + 1
            corrupted["player"]["active_details"][0]["speed"] = impossible
            corrupted["player"]["team"][0]["speed"] = impossible
            independent_root = worker.create_state(
                battle_format=CHAMPIONS_FORMAT,
                p1_team=OPPONENT_TEAM,
                p2_team=_pin_known_team_genders(SMOKE_TEAM, view["request"]),
                p1_preview=P1_PREVIEW, p2_preview=P2_PREVIEW,
                p1_name=view["opponent"]["name"],
                p2_name=view["player"]["name"],
                seed=SEED,
            )
            rejected = worker.materialize_present_hypotheses(
                state=independent_root, current_view=corrupted, limit=2,
            )
            if rejected["outcomes"]:
                raise SystemExit("ERROR: corrupt own speed entered native world")
            if rejected["reason"] != "own-unburden-speed-unresolved":
                raise SystemExit(
                    f"ERROR: expected own speed diagnostic, got {rejected['reason']}"
                )
            diagnostic = rejected.get("own_speed_diagnostic")
            if not isinstance(diagnostic, dict):
                raise SystemExit("ERROR: own native speed diagnostic was lost")
            # A native cached own Speed is not a stat-domain assertion.
            # In particular, only game-state admission checks may decide
            # whether an own observation matches current mechanics.
            if diagnostic["observed_speed"] != corrupted["player"]["team"][0]["speed"]:
                raise SystemExit("ERROR: diagnostic did not preserve public cached Speed")
            if not (
                diagnostic["species"] == "Sneasler"
                and diagnostic["slot"] == 0
                and diagnostic["observed_speed"] == impossible
                and diagnostic["stage"] == "after-native-unburden-removal"
                and diagnostic["unburden_volatile"] is False
                and diagnostic["pre_removal_action_speed"] > diagnostic["native_action_speed"]
            ):
                raise SystemExit("ERROR: incorrect own-only Unburden diagnostic")
            if set(diagnostic) - {
                "stage", "slot", "species", "observed_speed",
                "native_cached_speed", "native_action_speed",
                "native_stored_speed", "speed_boost", "status", "ability",
                "item", "unburden_volatile", "trick_room", "terrain",
                "weather", "pre_removal_action_speed",
            }:
                raise SystemExit("ERROR: speed diagnostic leaked unrelated state")
            # Transport fault injection on an ACTUAL pinned native mismatch,
            # rather than on an invented diagnostic-shaped fixture. The
            # rejected world stays rejected and its mechanical cause survives.
            broken = deepcopy(rejected)
            broken["own_speed_diagnostic"]["native_stored_speed"] = None
            with patch.object(worker, "request", return_value=broken):
                try:
                    worker.materialize_present_hypotheses(
                        state=independent_root, current_view=corrupted, limit=2,
                    )
                except OwnSpeedDiagnosticTransportError as error:
                    if (
                        error.mechanics_reason != "own-unburden-speed-unresolved"
                        or error.mismatch_path != "$.player.active_details[0].speed"
                        or error.issue != "invalid:native_stored_speed"
                    ):
                        raise SystemExit("ERROR: native mismatch lost its cause")
                else:
                    raise SystemExit("ERROR: bad Speed diagnostic was accepted")
            print("Impossible own-speed negative control rejected with diagnostics: YES")
            print("Malformed native diagnostic preserves original Speed rejection: YES")
        print(f"Unburden switch={switched}: speed {first['speed']} -> {now['speed']}; "
              f"admitted {len(report.particles)}")
        return first["speed"], now["speed"]
    finally:
        worker.close_session(sid)



def trick_room_speed_lifecycle(worker):
    """Record genuine cached-Speed signs across pinned Champions Trick Room expiry.

    A negative cached value is NOT interchangeable with a negative stat.
    Session snapshots are offline-only oracles and never enter inference.
    """
    start = worker.start_session(
        battle_format=CHAMPIONS_FORMAT, p1_team=OPPONENT_TEAM,
        p2_team=SMOKE_TEAM, p1_name="Public Opponent",
        p2_name="Practice AI", seed=SEED,
    )
    sid = start["session_id"]
    samples = []
    try:
        worker.choose_session(sid, p1_choice=P1_PREVIEW, p2_choice=P2_PREVIEW)
        for turn_index in range(6):
            view = worker.session_view(sid, side="p2")["view"]
            snapshot = worker.request("session_snapshot", session_id=sid)
            native = snapshot["state"]["sides"][1]["pokemon"][0]
            observed = view["player"]["active_details"][0]
            if observed["speed"] != native["speed"]:
                raise SystemExit("ERROR: Trick Room trace lost native cached-Speed provenance")
            active = "trickroom" in snapshot["state"]["field"]["pseudoWeather"]
            samples.append((active, observed["speed"]))
            if turn_index == 5:
                break
            own_choice = (
                "move protect, move trickroom"
                if turn_index == 0 else "move protect, move followme"
            )
            if own_choice not in worker.session_legal_choices(sid, side="p2"):
                raise SystemExit(f"ERROR: missing Trick Room trace choice: {own_choice}")
            if PROTECT not in worker.session_legal_choices(sid, side="p1"):
                raise SystemExit("ERROR: opponent Protect unavailable during Trick Room trace")
            worker.choose_session(sid, p1_choice=PROTECT, p2_choice=own_choice)
        if not any(active for active, _ in samples):
            raise SystemExit("ERROR: Trick Room never became active")
        if samples[-1][0]:
            raise SystemExit("ERROR: Trick Room failed to expire in trace")
        print(f"Pinned Trick Room native cached-Speed lifecycle: {samples}")
    finally:
        worker.close_session(sid)



def trick_room_unburden_matrix(worker, switched):
    """Characterize orthogonal Trick Room / Unburden native states.

    This intentionally does not require current-world admission: the known
    negative-cache issue is an expected failure in production until fixed.
    All private snapshots stay inside this offline regression test.
    """
    start = worker.start_session(
        battle_format=CHAMPIONS_FORMAT, p1_team=OPPONENT_TEAM,
        p2_team=SMOKE_TEAM, p1_name="Public Opponent",
        p2_name="Practice AI", seed=SEED,
    )
    sid = start["session_id"]
    seen = set()
    samples = []
    try:
        worker.choose_session(sid, p1_choice=P1_PREVIEW, p2_choice=P2_PREVIEW)
        for step in range(6):
            view = worker.session_view(sid, side="p2")["view"]
            snapshot = worker.request("session_snapshot", session_id=sid)
            native = snapshot["state"]["sides"][1]["pokemon"][0]
            trick_room = "trickroom" in snapshot["state"]["field"]["pseudoWeather"]
            unburden = "unburden" in native.get("volatiles", {})
            # During the switched run, Sneasler is on the bench at step 2:
            # active_details[0] refers to the replacement, not Sneasler.
            if switched and step == 2:
                if view["player"]["active_details"][0]["species"] == "Sneasler":
                    raise SystemExit("ERROR: expected Sneasler to be switched out")
                observed_speed = view["player"]["team"][0]["speed"]
                if native["speed"] != observed_speed:
                    raise SystemExit("ERROR: benched Sneasler cached Speed mismatch")
            else:
                observed = view["player"]["active_details"][0]
                if observed["species"] != "Sneasler" or native["speed"] != observed["speed"]:
                    raise SystemExit("ERROR: state matrix did not preserve native own cache")
                if view["player"]["team"][0]["speed"] != observed["speed"]:
                    raise SystemExit("ERROR: state matrix own team/active cache disagrees")
                observed_speed = observed["speed"]
            if step >= 3:
                if unburden == switched:
                    raise SystemExit("ERROR: switch-dependent native Unburden state incorrect")
                seen.add((trick_room, unburden))
                # Both currently active and just-expired Trick Room must
                # admit a public-only current-state world. Keep every exact
                # own projection/request and legal-menu safeguard.
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
                        f"ERROR: TR={trick_room} Unburden={unburden} "
                        f"current-world admission failed: "
                        f"{report.unresolved_reason}; {report.rejection_reasons}"
                    )
                for particle in report.particles:
                    projection = worker.state_view(
                        state=particle.state, side="p2",
                        previews={
                            "p1": list(ledger.preview_species),
                            "p2": [mon["species"] for mon in view["player"]["team"]],
                        },
                    )
                    if projection["player"] != view["player"] or projection["request"] != view["request"]:
                        raise SystemExit("ERROR: TR/Unburden own projection/request mismatch")
                    if set(worker.legal_choices(state=particle.state, side="p2")) != set(legal):
                        raise SystemExit("ERROR: TR/Unburden native legal menu mismatch")
            samples.append((trick_room, unburden, observed_speed))
            if step == 5:
                break
            own_choice = (
                "move protect, move trickroom" if step == 0 else
                OWN_SWITCH if switched and step in (1, 2) else OWN_STAY
            )
            if own_choice not in worker.session_legal_choices(sid, side="p2"):
                raise SystemExit(f"ERROR: matrix own command illegal: {own_choice}")
            if PROTECT not in worker.session_legal_choices(sid, side="p1"):
                raise SystemExit("ERROR: matrix opponent Protect illegal")
            worker.choose_session(sid, p1_choice=PROTECT, p2_choice=own_choice)
        if (True, not switched) not in seen or (False, not switched) not in seen:
            raise SystemExit(f"ERROR: missing active/expired Trick Room states: {seen}")
        if switched and samples[-1][2] == samples[0][2] * -2:
            raise SystemExit("ERROR: switched-out Unburden incorrectly retained")
        if not switched and samples[-1][2] >= 0:
            raise SystemExit("ERROR: expected native stale negative cached Speed after expiry")
        print(f"Pinned TR/Unburden switched={switched}: {samples}")
    finally:
        worker.close_session(sid)


def main():
    with ShowdownSearchWorker() as worker:
        control = case(worker, False)
        switched = case(worker, True)
        trick_room_speed_lifecycle(worker)
        trick_room_unburden_matrix(worker, False)
        trick_room_unburden_matrix(worker, True)
    if control[0] != switched[0] or control[1] <= switched[1]:
        raise SystemExit("ERROR: control and switched speeds were not distinct")
    print("RESULT: both native Unburden lifecycles admitted with exact own speed")


if __name__ == "__main__":
    main()
