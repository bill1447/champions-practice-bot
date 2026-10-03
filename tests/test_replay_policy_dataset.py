from __future__ import annotations

import pytest

from champions_practice.replay_policy_dataset import (
    LEGAL_MENU_AUTHORITY,
    POLICY_EXAMPLE_SCHEMA,
    ReplayMenuAdapterError,
    adapt_replay_decision_to_policy_example,
    match_replay_joint_to_legal_menu,
    parse_legal_choice,
)


PARTY = (
    "Indeedee-F",
    "Sneasler",
    "Rillaboom",
    "Gardevoir",
)


def _move(
    slot: int,
    move: str,
    *,
    resolved_side: str = "p2",
    resolved_slot: int = 1,
    gimmicks: list[str] | None = None,
) -> dict:
    return {
        "slot": slot,
        "kind": "move",
        "move": move,
        "move_name": move,
        "gimmicks": list(gimmicks or []),
        "resolved_target": {
            "side": resolved_side,
            "slot": resolved_slot,
        },
        "selected_target": None,
        "target_authority": "resolved-public-target-only",
        "authority": "top-level-public-move",
    }


def _switch(slot: int, species: str) -> dict:
    return {
        "slot": slot,
        "kind": "switch",
        "switch_species": species,
        "authority": "reconstructed-pre-action-switch",
    }


def _label(*actions: dict, complete: bool = True, side: str = "p1") -> dict:
    return {
        "schema": "showdown-replay-joint-action-v1",
        "side": side,
        "identity_complete": complete,
        "exact_showdown_command_available": False,
        "actions": list(actions),
        "missing": [],
    }


def test_parser_preserves_target_and_transformation_tokens():
    parsed = parse_legal_choice(
        "move expandingforce +2, move closecombat -1 mega"
    )

    assert len(parsed) == 2
    assert parsed[0].kind == "move"
    assert parsed[0].move == "expandingforce"
    assert parsed[0].target == 2
    assert parsed[1].move == "closecombat"
    assert parsed[1].target == -1
    assert parsed[1].transformations == ("mega",)


def test_exact_move_joint_maps_to_one_legal_menu_entry():
    label = _label(
        _move(1, "Follow Me", resolved_side="p1", resolved_slot=1),
        _move(2, "Close Combat", resolved_slot=2),
    )
    menu = (
        "move followme, move closecombat +2",
        "move psychic +1, move closecombat +2",
        "move followme, move protect",
    )

    match = match_replay_joint_to_legal_menu(
        label,
        menu,
        side="p1",
        party_species=PARTY,
    )

    assert match.matched
    assert match.matched_choice == menu[0]
    assert match.matched_index == 0


def test_resolved_target_never_breaks_selected_target_ambiguity():
    label = _label(
        _move(1, "Psychic", resolved_slot=2),
        _move(2, "Close Combat", resolved_slot=2),
    )
    menu = (
        "move psychic +1, move closecombat +2",
        "move psychic +2, move closecombat +2",
    )

    match = match_replay_joint_to_legal_menu(
        label,
        menu,
        side="p1",
        party_species=PARTY,
    )

    assert not match.matched
    assert match.reason == "selected-target-ambiguous"
    assert match.candidates == menu
    assert match.ambiguity_dimensions == ("selected-target",)


def test_unique_legal_target_can_be_labeled_without_claiming_selected_target():
    label = _label(
        _move(1, "Psychic", resolved_slot=2),
        _move(2, "Protect", resolved_side="p1", resolved_slot=2),
    )
    menu = (
        "move psychic +2, move protect",
        "move followme, move protect",
    )

    match = match_replay_joint_to_legal_menu(
        label,
        menu,
        side="p1",
        party_species=PARTY,
    )

    assert match.matched
    assert match.matched_choice == "move psychic +2, move protect"


def test_switch_identity_uses_player_party_slot_species_mapping():
    label = _label(
        _switch(1, "Rillaboom"),
        _move(2, "Dire Claw", resolved_slot=1),
    )
    menu = (
        "switch 3, move direclaw +1",
        "switch 4, move direclaw +1",
        "move followme, move direclaw +1",
    )

    match = match_replay_joint_to_legal_menu(
        label,
        menu,
        side="p1",
        party_species=PARTY,
    )

    assert match.matched
    assert match.matched_choice == menu[0]


def test_duplicate_species_switch_mapping_abstains_instead_of_picking_slot():
    label = _label(
        _switch(1, "Rillaboom"),
        _move(2, "Protect", resolved_side="p1", resolved_slot=2),
    )
    party = ("Indeedee-F", "Sneasler", "Rillaboom", "Rillaboom")
    menu = (
        "switch 3, move protect",
        "switch 4, move protect",
    )

    match = match_replay_joint_to_legal_menu(
        label,
        menu,
        side="p1",
        party_species=party,
    )

    assert not match.matched
    assert match.reason == "switch-slot-ambiguous"
    assert match.ambiguity_dimensions == ("switch-slot",)


def test_no_mega_event_does_not_match_mega_command():
    label = _label(
        _move(1, "Psychic", resolved_slot=1),
        _move(2, "Protect", resolved_side="p1", resolved_slot=2),
    )
    menu = (
        "move psychic +1, move protect",
        "move psychic +1 mega, move protect",
    )

    match = match_replay_joint_to_legal_menu(
        label,
        menu,
        side="p1",
        party_species=PARTY,
    )

    assert match.matched
    assert match.matched_choice == menu[0]


def test_generic_public_mega_event_abstains_between_x_and_y_variants():
    label = _label(
        _move(1, "Flamethrower", resolved_slot=1, gimmicks=["mega"]),
        _move(2, "Protect", resolved_side="p1", resolved_slot=2),
    )
    menu = (
        "move flamethrower +1 megax, move protect",
        "move flamethrower +1 megay, move protect",
    )

    match = match_replay_joint_to_legal_menu(
        label,
        menu,
        side="p1",
        party_species=PARTY,
    )

    assert not match.matched
    assert match.reason == "gimmick-variant-ambiguous"
    assert match.ambiguity_dimensions == ("gimmick-variant",)


def test_incomplete_replay_label_is_an_abstention():
    label = _label(
        _move(2, "Close Combat", resolved_slot=2),
        complete=False,
    )

    match = match_replay_joint_to_legal_menu(
        label,
        ("move followme, move closecombat +2",),
        side="p1",
        party_species=PARTY,
    )

    assert not match.matched
    assert match.reason == "incomplete-replay-label"
    assert match.candidates == ()


def test_observed_action_not_present_in_menu_abstains():
    label = _label(
        _move(1, "Follow Me", resolved_side="p1", resolved_slot=1),
        _move(2, "Close Combat", resolved_slot=2),
    )

    match = match_replay_joint_to_legal_menu(
        label,
        ("move psychic +1, move protect",),
        side="p1",
        party_species=PARTY,
    )

    assert not match.matched
    assert match.reason == "observed-action-not-in-legal-menu"


def test_policy_example_preserves_exact_menu_and_game_group():
    label = _label(
        _move(1, "Follow Me", resolved_side="p1", resolved_slot=1),
        _move(2, "Close Combat", resolved_slot=2),
    )
    decision = {
        "turn": 3,
        "public_state": {
            "schema": "showdown-replay-public-state-v1",
            "turn": 3,
        },
        "joint_actions": {
            "p1": label,
            "p2": _label(
                _move(1, "Protect", side="p2") if False else _move(1, "Protect"),
                _move(2, "Dragon Pulse"),
                side="p2",
            ),
        },
    }
    menu = (
        "move followme, move closecombat +2",
        "move psychic +1, move closecombat +2",
    )

    example = adapt_replay_decision_to_policy_example(
        replay_id="gen9championsvgc2026regmc-123",
        game_group="gen9championsvgc2026regmc-123",
        decision=decision,
        side="p1",
        legal_choices=menu,
        party_species=PARTY,
        menu_authority=LEGAL_MENU_AUTHORITY,
        showdown_revision="a" * 40,
    )

    assert example["schema"] == POLICY_EXAMPLE_SCHEMA
    assert example["game_group"] == "gen9championsvgc2026regmc-123"
    assert example["legal_menu"] == list(menu)
    assert example["trainable"] is True
    assert example["label_choice"] == menu[0]
    assert example["label_index"] == 0
    assert example["menu_provenance"] == {
        "authority": LEGAL_MENU_AUTHORITY,
        "showdown_revision": "a" * 40,
    }


def test_policy_example_records_target_ambiguity_as_nontrainable():
    label = _label(
        _move(1, "Psychic", resolved_slot=2),
        _move(2, "Close Combat", resolved_slot=2),
    )
    decision = {
        "turn": 1,
        "public_state": {"turn": 1},
        "joint_actions": {"p1": label},
    }
    menu = (
        "move psychic +1, move closecombat +2",
        "move psychic +2, move closecombat +2",
    )

    example = adapt_replay_decision_to_policy_example(
        replay_id="replay-1",
        game_group="replay-1",
        decision=decision,
        side="p1",
        legal_choices=menu,
        party_species=PARTY,
        menu_authority=LEGAL_MENU_AUTHORITY,
        showdown_revision="b" * 40,
    )

    assert example["trainable"] is False
    assert example["label_choice"] is None
    assert example["abstention"]["reason"] == "selected-target-ambiguous"
    assert example["abstention"]["candidate_count"] == 2


def test_policy_example_refuses_untrusted_menu_authority():
    decision = {
        "turn": 1,
        "public_state": {"turn": 1},
        "joint_actions": {
            "p1": _label(
                _move(1, "Follow Me", resolved_side="p1", resolved_slot=1),
                _move(2, "Close Combat", resolved_slot=2),
            )
        },
    }

    with pytest.raises(ReplayMenuAdapterError, match="pinned-Showdown"):
        adapt_replay_decision_to_policy_example(
            replay_id="replay-1",
            game_group="replay-1",
            decision=decision,
            side="p1",
            legal_choices=("move followme, move closecombat +2",),
            party_species=PARTY,
            menu_authority="handwritten-menu",
            showdown_revision="c" * 40,
        )


def test_malformed_menu_fails_closed():
    label = _label(
        _move(1, "Follow Me", resolved_side="p1", resolved_slot=1),
        _move(2, "Close Combat", resolved_slot=2),
    )

    with pytest.raises(ReplayMenuAdapterError, match="duplicate"):
        match_replay_joint_to_legal_menu(
            label,
            (
                "move followme, move closecombat +2",
                "move followme, move closecombat +2",
            ),
            side="p1",
            party_species=PARTY,
        )

    with pytest.raises(ReplayMenuAdapterError, match="exceeds party mapping"):
        match_replay_joint_to_legal_menu(
            _label(
                _switch(1, "Rillaboom"),
                _move(2, "Protect"),
            ),
            ("switch 8, move protect",),
            side="p1",
            party_species=PARTY,
        )
