"""Pinned-native tenure equivalence and sleep/Flash Fire admission negatives.

Only offline assertions read oracle counters. Production is given the public
channel, owned inventory and a fixed public prior catalog.
"""

from dataclasses import replace
from copy import deepcopy

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.belief_controller import _pin_known_team_genders
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog
from champions_practice.persistent_support import (
    public_active_tenure_plan,
    public_opponent_pp_plan,
    public_support_contract,
    static_support_issue,
)
from champions_practice.present_mechanics import unsupported_present_mechanics
from champions_practice.present_rebase import (
    _positive_mechanics_rejection,
    _projection_mechanics_rejection,
    build_present_rebase,
)
from champions_practice.public_lifecycle import public_protection_plan
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.teams import SMOKE_TEAM


SEEDS = (
    "sodium,00000001000000020000000300000004",
    "sodium,00000005000000060000000700000008",
    "sodium,000000090000000a0000000b0000000c",
)
SPECIES = ("Incineroar", "Dragonite", "Metagross", "Rotom-Wash")


def fixture():
    pool = catalog()
    priors = {}
    for species in SPECIES:
        mon = pool[species][0]
        moves = tuple(
            "Psychic"
            if move == "Stomping Tantrum" and species == "Metagross"
            else "High Horsepower"
            if move == "Stomping Tantrum"
            else move
            for move in mon.moves
        )
        # Protect provides a harmless completed native move for every actor.
        if species == "Incineroar":
            moves = ("Fake Out", "Darkest Lariat", "Parting Shot", "Protect")
        priors[species] = (replace(mon, moves=moves, item=""),)
    team = "\n\n".join(priors[species][0].team_text for species in SPECIES)
    return team, priors


def advance(worker, state, ledger, previews, p1, p2, seed=SEEDS[0]):
    state = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": p1,
                "p2_choice": p2,
                "rng_seed": seed,
                "include_state": True,
            }
        ],
    )[0]["state"]
    view = worker.state_view(state=state, side="p2", previews=previews)
    return state, ledger.advance(view), view


def assert_tenure(worker, root, current, view, ledger, previews, priors):
    saw_flinch = False
    plan = public_active_tenure_plan(view, ledger)
    assert plan is not None
    for entry in plan:
        oracle = current["sides"][1 if entry["side"] == "player" else 0]["pokemon"][entry["slot"]]
        assert (entry["move_actions"], entry["active_turns"]) == (
            oracle["activeMoveActions"],
            oracle["activeTurns"],
        ), (entry, oracle["activeMoveActions"], oracle["activeTurns"])
    probe = worker.materialize_present_hypotheses(
        state=root,
        current_view=view,
        protection_plan=public_protection_plan(view, ledger),
        active_tenure_plan=plan,
        opponent_pp_plan=public_opponent_pp_plan(view, ledger),
    )
    assert probe["outcomes"], (probe.get("reason"), probe.get("mismatch_path"))
    legal = worker.legal_choices(state=current, side="p2")
    for outcome in probe["outcomes"]:
        candidate = outcome["state"]
        for side in (0, 1):
            for mon in current["sides"][side]["pokemon"]:
                rebuilt_mon = next(
                    entry
                    for entry in candidate["sides"][side]["pokemon"]
                    if entry["set"]["species"] == mon["set"]["species"]
                )
                assert [(m["id"], m["pp"], m["maxpp"]) for m in mon["moveSlots"]] == [
                    (m["id"], m["pp"], m["maxpp"]) for m in rebuilt_mon["moveSlots"]
                ]
        projected = worker.state_view(state=candidate, side="p2", previews=previews)
        rejection = _positive_mechanics_rejection(
            candidate,
            projected,
            current_view=view,
            ledger=ledger,
            legal_live=tuple(legal),
            hypothetical_legal=worker.legal_choices(state=candidate, side="p2"),
        )
        assert rejection is None, rejection
        corrupted = deepcopy(candidate)
        stall = corrupted["sides"][0]["pokemon"][1]["volatiles"].get("stall")
        if stall:
            stall["counter"] = 1
            assert (
                _positive_mechanics_rejection(
                    corrupted,
                    projected,
                    current_view=view,
                    ledger=ledger,
                    legal_live=tuple(legal),
                    hypothetical_legal=worker.legal_choices(state=candidate, side="p2"),
                )
                == "unsupported-persistent:protection-mismatch"
            )
        for side in ("p1", "p2"):
            assert worker.legal_choices(state=candidate, side=side) == worker.legal_choices(
                state=current, side=side
            )
        # Compare relevant next-turn effects at matched RNG. Protection itself
        # has stochastic history, so use a non-protection attack in both slots.
        choices = {
            side: min(
                (
                    choice
                    for choice in worker.legal_choices(state=current, side=side)
                    if view["phase"] == "switch"
                    or (
                        "switch" not in choice
                        and "protect" not in choice
                        and "partingshot" not in choice
                    )
                ),
                key=lambda choice: (not choice.startswith("move fakeout +1"), choice),
            )
            for side in ("p1", "p2")
        }
        for seed in SEEDS:
            children = [
                worker.branch_many(
                    state=state,
                    branches=[
                        {
                            "p1_choice": choices["p1"],
                            "p2_choice": choices["p2"],
                            "rng_seed": seed,
                            "include_state": True,
                        }
                    ],
                )[0]["state"]
                for state in (current, candidate)
            ]
            for side in (0, 1):
                actual = children[0]["sides"][side]["pokemon"][:2]
                rebuilt = children[1]["sides"][side]["pokemon"][:2]
                for slot, (a, b) in enumerate(zip(actual, rebuilt)):
                    assert (
                        a["status"],
                        a["activeMoveActions"],
                        a["activeTurns"],
                        a["fainted"],
                    ) == (b["status"], b["activeMoveActions"], b["activeTurns"], b["fainted"])
                    # HP intervals are opponent hypotheses, not exact oracle HP.
                    assert a["maxhp"] == b["maxhp"]
                    assert a["boosts"] == b["boosts"]
                    before_a = current["sides"][side]["pokemon"][slot]
                    before_b = candidate["sides"][side]["pokemon"][slot]
                    assert before_a["hp"] - a["hp"] == before_b["hp"] - b["hp"]
            event_views = [
                worker.state_view(state=child, side="p2", previews=previews) for child in children
            ]
            flinches = [
                [
                    event
                    for event in v["public_event_delta"]["events"]
                    if event[0] == "cant" and event[2] == "flinch"
                ]
                for v in event_views
            ]
            assert flinches[0] == flinches[1]
            saw_flinch |= bool(flinches[0])
    # Exercise the full production constructor, including all prior support.
    report = build_present_rebase(
        worker,
        ledger=ledger,
        current_view=view,
        priors=priors,
        battle_format=CHAMPIONS_FORMAT,
        ai_team=_pin_known_team_genders(fixture()[0], view["request"]),
        ai_preview_choice="team 1234",
        legal_live=tuple(legal),
    )
    assert report.particles, report.unresolved_reason
    return saw_flinch


def tenure_controls(worker):
    team, priors = fixture()
    previews = {side: list(SPECIES) for side in ("p1", "p2")}
    for seed in SEEDS:
        saw_flinch = False
        root = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=team,
            p2_team=team,
            p1_preview="team 1234",
            p2_preview="team 1234",
            seed=seed,
        )
        current = root
        ledger = PublicConstraintLedger.from_public_view(
            worker.state_view(state=root, side="p2", previews=previews)
        )
        for p1, p2 in (
            ("move darkestlariat +2, move protect", "move darkestlariat +2, move protect"),
            ("switch 3, move protect", "switch 3, move protect"),
            ("switch 3, move protect", "switch 3, move protect"),
            ("move fakeout +2, move protect", "move fakeout +2, move protect"),
        ):
            current, ledger, view = advance(worker, current, ledger, previews, p1, p2, seed)
            if view["turn"] == 2:
                old = worker.materialize_present_hypotheses(
                    state=root,
                    current_view=view,
                    protection_plan=public_protection_plan(view, ledger),
                )
                assert not old["outcomes"] and old["reason"] == "exact-own-request-mismatch"
            saw_flinch |= assert_tenure(worker, root, current, view, ledger, previews, priors)
        assert saw_flinch, (
            "positive first-entry Fake Out must really flinch in the next-turn control"
        )
        print(
            "Pinned Fake Out: both sides, continuing entry, switch out/back, matched next-turn outcomes"
        )


def opponent_fakeout_negative(worker):
    team, _ = fixture()
    previews = {side: list(SPECIES) for side in ("p1", "p2")}
    root = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=team,
        p2_team=team,
        p1_preview="team 1234",
        p2_preview="team 3412",
        seed=SEEDS[0],
    )
    ledger = PublicConstraintLedger.from_public_view(
        worker.state_view(state=root, side="p2", previews=previews),
    )
    current, ledger, view = advance(
        worker,
        root,
        ledger,
        previews,
        "move darkestlariat +2, move protect",
        "move protect, move protect",
    )
    old = worker.materialize_present_hypotheses(
        state=root, current_view=view, protection_plan=public_protection_plan(view, ledger)
    )
    assert old["outcomes"], old.get("reason")
    candidate = old["outcomes"][0]["state"]
    projected = worker.state_view(state=candidate, side="p2", previews=previews)
    kwargs = dict(
        current_view=view,
        ledger=ledger,
        legal_live=tuple(worker.legal_choices(state=current, side="p2")),
        hypothetical_legal=worker.legal_choices(state=candidate, side="p2"),
    )
    assert _projection_mechanics_rejection(candidate, projected, **kwargs) is None
    assert not any("fakeout" in choice for choice in worker.legal_choices(state=current, side="p1"))
    assert any("fakeout" in choice for choice in worker.legal_choices(state=candidate, side="p1"))
    assert (
        _positive_mechanics_rejection(candidate, projected, **kwargs)
        == "unsupported-persistent:active-tenure-mismatch"
    )
    print(
        "Pinned opponent Fake Out: old projection admits phantom threat; closed admission rejects it"
    )


def boundary_controls(worker):
    team, priors = fixture()
    previews = {side: list(SPECIES) for side in ("p1", "p2")}
    # A real Parting Shot pauses in the middle of a turn. No incomplete queue
    # can be represented by a fresh root; resume the native pivot before admission.
    root = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=team,
        p2_team=team,
        p1_preview="team 1234",
        p2_preview="team 1234",
        seed=SEEDS[0],
    )
    ledger = PublicConstraintLedger.from_public_view(
        worker.state_view(state=root, side="p2", previews=previews)
    )
    current, ledger, view = advance(
        worker,
        root,
        ledger,
        previews,
        "move darkestlariat +2, move protect",
        "move partingshot +1, move protect",
    )
    assert view["phase"] == "switch"
    assert unsupported_present_mechanics(view, ledger) == "unsupported-public-switch-boundary"
    current, ledger, view = advance(worker, current, ledger, previews, "wait", "switch 3, pass")
    assert view["phase"] == "move"
    assert_tenure(worker, root, current, view, ledger, previews, priors)
    print("Pinned mid-turn pivot: reject pending queue, reconstruct after native completion")

    # Actual KO and post-upkeep forced replacement, using native damage only.
    root = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=team,
        p2_team=team,
        p1_preview="team 4321",
        p2_preview="team 1234",
        seed=SEEDS[0],
    )
    ledger = PublicConstraintLedger.from_public_view(
        worker.state_view(state=root, side="p2", previews=previews)
    )
    current, ledger, _ = advance(
        worker,
        root,
        ledger,
        previews,
        "move hydropump +1, move psychic +1",
        "move protect, move protect",
    )
    for _ in range(5):
        current, ledger, view = advance(
            worker,
            current,
            ledger,
            previews,
            "move hydropump +1, move psychic +1",
            "move darkestlariat +2, move protect",
        )
        if view["phase"] == "switch":
            break
    assert view["phase"] == "switch" and view["player"]["active_details"][0]["fainted"]
    # The pending post-residual board has a canonical native empty queue.
    assert_tenure(worker, root, current, view, ledger, previews, priors)
    current, ledger, view = advance(worker, current, ledger, previews, "wait", "switch 3, pass")
    assert_tenure(worker, root, current, view, ledger, previews, priors)
    print("Pinned fainted replacement: post-upkeep pause and new entry tenure match")


def reject_before_construction(worker, view, ledger, reason):
    assert unsupported_present_mechanics(view, ledger) == reason

    class NoWorker:
        def __getattr__(self, name):
            raise AssertionError("unresolved persistent state reached native construction: " + name)

    report = build_present_rebase(
        NoWorker(),
        ledger=ledger,
        current_view=view,
        priors={},
        battle_format=CHAMPIONS_FORMAT,
        ai_team=SMOKE_TEAM,
        ai_preview_choice="team 1234",
    )
    assert not report.particles and report.roots_tried == 0 and report.unresolved_reason == reason


def latent_negatives(worker):
    # Real native sleep from an opponent Venusaur, not an injected status.
    team = "\n\n".join(
        catalog()[species][0].team_text
        for species in ("Venusaur", "Dragonite", "Incineroar", "Metagross")
    )
    previews = {
        "p1": ["Venusaur", "Dragonite", "Incineroar", "Metagross"],
        "p2": ["Indeedee-F", "Sneasler", "Gardevoir", "Armarouge", "Rillaboom", "Metagross"],
    }
    witnessed = 0
    sleep_reset_witnesses = 0
    for seed in SEEDS:
        root = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=team,
            p2_team=SMOKE_TEAM,
            p1_preview="team 1234",
            p2_preview="team 6431",
            seed=seed,
        )
        ledger = PublicConstraintLedger.from_public_view(
            worker.state_view(state=root, side="p2", previews=previews)
        )
        current, ledger, view = advance(
            worker,
            root,
            ledger,
            previews,
            "move sleeppowder +1, move protect",
            "move psychicfangs +1, move protect",
            seed,
        )
        if any(mon.get("status") == "slp" for mon in view["player"]["team"]):
            old_probe = worker.materialize_present_hypotheses(state=root, current_view=view)
            assert old_probe["outcomes"], old_probe.get("reason")
            actual = current["sides"][1]["pokemon"][0]
            old = old_probe["outcomes"][0]["state"]["sides"][1]["pokemon"][0]
            sleep_reset_witnesses += actual["statusState"]["time"] != old["statusState"]["time"]
            reject_before_construction(worker, view, ledger, "unsupported-persistent:status:slp")
            witnessed += 1
    assert witnessed >= 1
    assert sleep_reset_witnesses >= 1, "old constructor must demonstrate a fresh sleep counter"
    # Native Flash Fire activation in the shipped mirror roster.
    previews = {side: previews["p2"] for side in ("p1", "p2")}
    root = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=SMOKE_TEAM,
        p2_team=SMOKE_TEAM,
        p1_preview="team 3456",
        p2_preview="team 4653",
        seed=SEEDS[0],
    )
    ledger = PublicConstraintLedger.from_public_view(
        worker.state_view(state=root, side="p2", previews=previews)
    )
    current, ledger, view = advance(
        worker,
        root,
        ledger,
        previews,
        "move mysticalfire +1, move protect",
        "move wideguard, move protect",
    )
    assert current["sides"][1]["pokemon"][0]["volatiles"].get("flashfire")
    old_probe = worker.materialize_present_hypotheses(state=root, current_view=view)
    assert old_probe["outcomes"], old_probe.get("reason")
    assert (
        "flashfire" not in old_probe["outcomes"][0]["state"]["sides"][1]["pokemon"][0]["volatiles"]
    )
    reject_before_construction(worker, view, ledger, "unsupported-persistent:volatile:flashfire")
    print("Pinned sleep and Flash Fire: real native histories rejected before fresh construction")


def remaining_mechanic_controls(worker):
    # Isolated native callback controls. These synthetic move inventories are
    # not a team-import acceptance test or a claim about format learnsets.
    # Each tests observed persistent state and fails admission explicitly.
    team, _ = fixture()
    for move, effect, volatile in (
        ("Encore", "encore", "encore"),
        ("Taunt", "taunt", "taunt"),
        ("Imprison", "imprison", "imprison"),
        ("Substitute", "substitute", "substitute"),
        ("Confuse Ray", "confusion", "confusion"),
        ("Salt Cure", "saltcure", "saltcure"),
        ("Perish Song", "perish", "perishsong"),
        ("Toxic", "tox", None),
    ):
        # Use one real native move, with a harmless partner and victim move.
        probe_team = team.replace("- Fake Out", "- " + move)
        previews = {side: list(SPECIES) for side in ("p1", "p2")}
        root = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=probe_team,
            p2_team=team,
            p1_preview="team 1234",
            p2_preview="team 4312" if move == "Toxic" else "team 3412",
            seed=SEEDS[0],
        )
        ledger = PublicConstraintLedger.from_public_view(
            worker.state_view(state=root, side="p2", previews=previews)
        )
        current = root
        if move == "Encore":
            current, ledger, _ = advance(
                worker,
                current,
                ledger,
                previews,
                "move darkestlariat +2, move protect",
                "move psychic +2, move protect",
            )
        move_id = "".join(c for c in move.lower() if c.isalnum())
        target = "" if move in {"Imprison", "Substitute", "Perish Song"} else " +1"
        current, ledger, view = advance(
            worker,
            current,
            ledger,
            previews,
            f"move {move_id}{target}, move protect",
            "move thunderbolt +2, move protect"
            if move == "Toxic"
            else "move psychic +2, move protect",
        )
        mons = [mon for side in current["sides"] for mon in side["pokemon"][:2]]
        if volatile:
            assert any(volatile in mon["volatiles"] for mon in mons), (
                move,
                view["public_event_delta"],
            )
        else:
            assert any(mon["status"] == effect for mon in mons), move
        contract = public_support_contract(view, ledger)
        assert contract.unresolved_reason is not None, move
        assert any(
            entry.classification == "unresolved" and effect in entry.mechanic
            for entry in contract.mechanics
        ), (move, contract)
        assert unsupported_present_mechanics(view, ledger) is not None, move
        print(f"Pinned {move}: native persistent state observed; admission unresolved")
    choice_team = team.replace("Incineroar\n", "Incineroar @ Choice Band\n")
    root = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=choice_team,
        p2_team=team,
        p1_preview="team 1234",
        p2_preview="team 3412",
        seed=SEEDS[0],
    )
    ledger = PublicConstraintLedger.from_public_view(
        worker.state_view(state=root, side="p2", previews=previews)
    )
    current, _, _ = advance(
        worker,
        root,
        ledger,
        previews,
        "move darkestlariat +2, move protect",
        "move psychic +2, move protect",
    )
    assert "choicelock" in current["sides"][0]["pokemon"][0]["volatiles"]
    assert static_support_issue(
        ability="Intimidate", item="Choice Band", moves=["Darkest Lariat"], opponent=True
    )
    print("Pinned choice lock: native silent volatile observed; hypothetical item rejected")


def uncertainty_control(worker):
    # Publicly unrevealed source item: retain ordinary and extended terrain
    # worlds. Neither the live oracle nor the lack of a reveal picks one.
    _, priors = fixture()
    rillaboom = replace(catalog()["Rillaboom"][0], item="")
    names = ("Rillaboom", "Dragonite", "Metagross", "Rotom-Wash")
    priors = {name: priors[name] for name in names if name in priors}
    priors["Rillaboom"] = (rillaboom, replace(rillaboom, item="Terrain Extender"))
    team = "\n\n".join(priors[name][0].team_text for name in names)
    previews = {side: list(names) for side in ("p1", "p2")}
    root = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=team,
        p2_team=team,
        p1_preview="team 1234",
        p2_preview="team 3412",
        seed=SEEDS[0],
    )
    ledger = PublicConstraintLedger.from_public_view(
        worker.state_view(state=root, side="p2", previews=previews)
    )
    current, ledger, view = advance(
        worker, root, ledger, previews, "move protect, move protect", "move protect, move protect"
    )
    source = next(mon for mon in view["opponent"]["revealed"] if mon["species"] == "Rillaboom")
    assert not source["items"], "source item must remain publicly unrevealed"
    report = build_present_rebase(
        worker,
        ledger=ledger,
        current_view=view,
        priors=priors,
        battle_format=CHAMPIONS_FORMAT,
        ai_team=_pin_known_team_genders(team, view["request"]),
        ai_preview_choice="team 3412",
        legal_live=tuple(worker.legal_choices(state=current, side="p2")),
        max_roots=2,
        max_particles=4,
    )
    assert report.particles, report.unresolved_reason
    assert {
        particle.state["field"]["terrainState"]["duration"] for particle in report.particles
    } == {4, 7}
    candidate = report.particles[0].state
    corrupted = deepcopy(candidate)
    corrupted["field"]["terrainState"]["duration"] += 1
    assert (
        _positive_mechanics_rejection(
            corrupted,
            worker.state_view(state=candidate, side="p2", previews=previews),
            current_view=view,
            ledger=ledger,
            legal_live=tuple(worker.legal_choices(state=current, side="p2")),
            hypothetical_legal=worker.legal_choices(state=candidate, side="p2"),
        )
        == "unsupported-persistent:field-duration-mismatch"
    )
    assert report.exhaustively_excluded_worlds == 0
    print("Pinned uncertainty: unrevealed source item retains both native terrain-duration worlds")


def main():
    with ShowdownSearchWorker(startup_timeout_seconds=60) as worker:
        tenure_controls(worker)
        opponent_fakeout_negative(worker)
        boundary_controls(worker)
        latent_negatives(worker)
        remaining_mechanic_controls(worker)
        uncertainty_control(worker)
    print("RESULT: tested persistent contract negatives and Fake Out outcome equivalence passed")


if __name__ == "__main__":
    main()
