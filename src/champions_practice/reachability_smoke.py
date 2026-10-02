"""Pinned-Showdown smoke for witness and zero-draw disproof authority."""

from champions_practice.config import CHAMPIONS_FORMAT
import copy

from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.reachability import (
    PublicReachabilityStep,
    ReachabilityStatus,
    evaluate_deterministic_public_transition,
    public_reachability_observation_issue,
    witness_public_observation_sequence,
)
from champions_practice.search_worker import HypotheticalSearchWorker
from champions_practice.teams import SMOKE_TEAM


P1_PREVIEW = "team 1256"
P2_PREVIEW = "team 4512"
P1_CHOICE = "move psychic +1, move protect"
P2_CHOICE = "move expandingforce +1, move protect"
WITNESS_SEED = (
    "sodium,1111111111111111111111111111111111111111111111111111111111111111"
)
ALT_SEEDS = tuple(
    f"sodium,{digit * 64}"
    for digit in "23456789abcdef"
)


PRODUCER_P1_TEAM = """Smeargle
Ability: Own Tempo
Level: 50
- Thunderbolt
- Power Swap
- Psych Up
- Super Fang

Chansey
Ability: Natural Cure
Level: 50
- Protect
- Soft-Boiled
- Helping Hand
- Seismic Toss

Armarouge
Ability: Flash Fire
Level: 50
- Protect
- Psychic
- Armor Cannon
- Wide Guard

Gardevoir
Ability: Trace
Level: 50
- Protect
- Psychic
- Hyper Voice
- Mystical Fire
"""

PRODUCER_P2_TEAM = """Garchomp
Ability: Rough Skin
Level: 50
EVs: 1 HP
- Splash
- Protect
- Tackle
- Swords Dance

Chansey
Ability: Natural Cure
Level: 50
- Protect
- Soft-Boiled
- Helping Hand
- Seismic Toss

Armarouge
Ability: Flash Fire
Level: 50
- Protect
- Psychic
- Armor Cannon
- Wide Guard

Gardevoir
Ability: Trace
Level: 50
- Protect
- Psychic
- Hyper Voice
- Mystical Fire
"""

PRODUCER_PREVIEW = "team 1234"
PRODUCER_P2_CHOICE = "move splash, move protect"
PRODUCER_SEEDS = (
    None,
    "sodium,1111111111111111111111111111111111111111111111111111111111111111",
    "sodium,2222222222222222222222222222222222222222222222222222222222222222",
    "sodium,3333333333333333333333333333333333333333333333333333333333333333",
)


def _contains_event(
    view: dict,
    event_name: str,
    expected_piece: str | None = None,
) -> bool:
    events = view.get("public_event_delta", {}).get("events", [])
    for event in events:
        if not isinstance(event, list) or not event or event[0] != event_name:
            continue
        if expected_piece is None or expected_piece in event:
            return True
    return False


def _assert_real_producer_variant(
    worker: HypotheticalSearchWorker,
    *,
    p1_choice: str,
    event_name: str,
    expected_piece: str | None = None,
) -> None:
    state = worker.create_state(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=PRODUCER_P1_TEAM,
        p2_team=PRODUCER_P2_TEAM,
        p1_preview=PRODUCER_PREVIEW,
        p2_preview=PRODUCER_PREVIEW,
        seed="sodium,87654321000000020000000300000004",
    )
    candidates = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": p1_choice,
                "p2_choice": PRODUCER_P2_CHOICE,
                "rng_seed": seed,
                "include_state": True,
                "view_side": "p1",
                "include_rng_draw_count": True,
            }
            for seed in PRODUCER_SEEDS
        ],
    )
    selected = next(
        (
            (seed, branch)
            for seed, branch in zip(PRODUCER_SEEDS, candidates, strict=True)
            if isinstance(branch.get("view"), dict)
            and _contains_event(branch["view"], event_name, expected_piece)
        ),
        None,
    )
    if selected is None:
        raise SystemExit(
            "ERROR: pinned producer-contract smoke did not emit "
            f"{event_name} / {expected_piece}"
        )

    seed, branch = selected
    view = branch["view"]
    issue = public_reachability_observation_issue(view)
    if issue is not None:
        raise SystemExit(
            "ERROR: genuine pinned producer view failed reachability schema: "
            f"{event_name}: {issue}"
        )

    step = PublicReachabilityStep(
        p1_choice=p1_choice,
        p2_choice=PRODUCER_P2_CHOICE,
        expected_public_view=view,
        rng_seeds=(seed,),
    )
    witnessed = witness_public_observation_sequence(
        worker,
        state=state,
        side="p1",
        steps=(step,),
    )
    if witnessed.status is not ReachabilityStatus.WITNESSED:
        raise SystemExit(
            "ERROR: genuine pinned producer variant was not witnessed: "
            f"{event_name}: {witnessed}"
        )

    if branch.get("rng_draw_count") == 0:
        deterministic = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p1",
            step=step,
        )
        if deterministic.status is not ReachabilityStatus.WITNESSED:
            raise SystemExit(
                "ERROR: zero-draw producer variant was not deterministic witness: "
                f"{event_name}: {deterministic}"
            )


def _assert_real_producer_variants(worker: HypotheticalSearchWorker) -> None:
    _assert_real_producer_variant(
        worker,
        p1_choice="move thunderbolt +1, move protect",
        event_name="-immune",
    )
    _assert_real_producer_variant(
        worker,
        p1_choice="move powerswap +1, move protect",
        event_name="-swapboost",
        expected_piece="atkspa",
    )
    _assert_real_producer_variant(
        worker,
        p1_choice="move psychup +1, move protect",
        event_name="-copyboost",
        expected_piece="[from]:move:psychup",
    )
    _assert_real_producer_variant(
        worker,
        p1_choice="move superfang +1, move protect",
        event_name="-damage",
        expected_piece="50/100y",
    )


def _active_hp(view: dict) -> tuple[tuple[float, ...], tuple[float, ...]]:
    player = tuple(
        float(pokemon["hp_percent"])
        for pokemon in view["player"]["active_details"]
        if isinstance(pokemon, dict)
    )
    opponent = tuple(
        float(pokemon["hp_percent"])
        for pokemon in view["opponent"]["active"]
        if isinstance(pokemon, dict)
    )
    return player, opponent


def main() -> None:
    with HypotheticalSearchWorker() as worker:
        state = worker.create_state(
            battle_format=CHAMPIONS_FORMAT,
            p1_team=SMOKE_TEAM,
            p2_team=SMOKE_TEAM,
            p1_preview=P1_PREVIEW,
            p2_preview=P2_PREVIEW,
            seed=(
                "sodium,87654321000000020000000300000004"
            ),
        )
        before = worker.state_view(state=state, side="p2")
        target_branch = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": P1_CHOICE,
                    "p2_choice": P2_CHOICE,
                    "rng_seed": WITNESS_SEED,
                    "include_state": True,
                    "view_side": "p2",
                }
            ],
        )[0]
        if "rng_draw_count" in target_branch:
            raise SystemExit(
                "ERROR: PRNG draw metadata leaked from a non-opt-in branch"
            )
        target = target_branch.get("view")
        if not isinstance(target, dict):
            raise SystemExit("ERROR: witness fixture produced no public view")
        if _active_hp(before) == _active_hp(target):
            raise SystemExit(
                "ERROR: reachability fixture did not produce public damage"
            )

        witnessed = witness_public_observation_sequence(
            worker,
            state=state,
            side="p2",
            steps=(
                PublicReachabilityStep(
                    p1_choice=P1_CHOICE,
                    p2_choice=P2_CHOICE,
                    expected_public_view=target,
                    rng_seeds=(WITNESS_SEED,),
                ),
            ),
        )
        if witnessed.status is not ReachabilityStatus.WITNESSED:
            raise SystemExit(
                f"ERROR: known Showdown witness was not retained: {witnessed}"
            )

        alternatives = worker.branch_many(
            state=state,
            branches=[
                {
                    "p1_choice": P1_CHOICE,
                    "p2_choice": P2_CHOICE,
                    "rng_seed": seed,
                    "include_state": True,
                    "view_side": "p2",
                }
                for seed in ALT_SEEDS
            ],
        )
        wanted = public_observation_signature(target)
        miss_seed = next(
            (
                seed
                for seed, branch in zip(ALT_SEEDS, alternatives, strict=True)
                if isinstance(branch.get("view"), dict)
                and public_observation_signature(branch["view"]) != wanted
            ),
            None,
        )
        if miss_seed is None:
            raise SystemExit(
                "ERROR: reachability smoke could not find a distinct RNG outcome"
            )

        missed = witness_public_observation_sequence(
            worker,
            state=state,
            side="p2",
            steps=(
                PublicReachabilityStep(
                    p1_choice=P1_CHOICE,
                    p2_choice=P2_CHOICE,
                    expected_public_view=target,
                    rng_seeds=(miss_seed,),
                ),
            ),
        )
        if missed.status is not ReachabilityStatus.UNRESOLVED:
            raise SystemExit(
                "ERROR: bounded non-witness became conclusive mechanics evidence: "
                f"{missed}"
            )
        if missed.establishes_impossibility:
            raise SystemExit(
                "ERROR: finite RNG miss was promoted to impossibility"
            )

        deterministic_candidates = (
            (
                "move followme, switch 3",
                "move wideguard, switch 4",
            ),
            (
                "switch 3, switch 4",
                "switch 3, switch 4",
            ),
            (
                "move trickroom, switch 3",
                "move wideguard, switch 4",
            ),
        )
        deterministic = None
        for p1_choice, p2_choice in deterministic_candidates:
            if p1_choice not in worker.legal_choices(state=state, side="p1"):
                continue
            if p2_choice not in worker.legal_choices(state=state, side="p2"):
                continue
            branch = worker.branch_many(
                state=state,
                branches=[
                    {
                        "p1_choice": p1_choice,
                        "p2_choice": p2_choice,
                        "include_state": True,
                        "view_side": "p2",
                        "include_rng_draw_count": True,
                    }
                ],
            )[0]
            if branch.get("rng_draw_count") == 0 and isinstance(
                branch.get("view"),
                dict,
            ):
                deterministic = (p1_choice, p2_choice, branch["view"])
                break

        if deterministic is None:
            raise SystemExit(
                "ERROR: deterministic reachability smoke found no zero-draw fixture"
            )

        deterministic_p1, deterministic_p2, deterministic_view = deterministic

        malformed_targets = []
        empty_target = {}
        malformed_targets.append(("empty", empty_target))
        missing_event_delta = copy.deepcopy(deterministic_view)
        missing_event_delta.pop("public_event_delta")
        malformed_targets.append(("missing-event-ledger", missing_event_delta))
        malformed_unsupported = copy.deepcopy(deterministic_view)
        malformed_unsupported["public_event_delta"]["unsupported"] = (
            "future-mechanic"
        )
        malformed_targets.append(("malformed-unsupported", malformed_unsupported))

        truncated_damage = copy.deepcopy(deterministic_view)
        truncated_damage["public_event_delta"]["events"].append(["-damage"])
        malformed_targets.append(("truncated-damage-event", truncated_damage))

        unknown_event = copy.deepcopy(deterministic_view)
        unknown_event["public_event_delta"]["events"].append(
            ["-future-event", "p1a"]
        )
        malformed_targets.append(("unknown-mechanics-event", unknown_event))

        impossible_action = copy.deepcopy(deterministic_view)
        impossible_action["opponent_last_actions"].append(
            {
                "turn": max(1, deterministic_view["turn"]),
                "slot": 999,
                "move": "definitelynotamove",
                "target": 999,
            }
        )
        malformed_targets.append(("impossible-selected-action", impossible_action))

        boolean_action = copy.deepcopy(deterministic_view)
        boolean_action["opponent_last_actions"].append(
            {
                "turn": max(1, deterministic_view["turn"]),
                "slot": True,
                "move": "tackle",
                "target": 1,
            }
        )
        malformed_targets.append(("boolean-selected-slot", boolean_action))

        malformed_condition = copy.deepcopy(deterministic_view)
        malformed_condition["public_event_delta"]["events"].append(
            ["-damage", "p1a", "garbage"]
        )
        malformed_targets.append(("malformed-damage-condition", malformed_condition))

        incomplete_mega = copy.deepcopy(deterministic_view)
        incomplete_mega["public_event_delta"]["events"].append(
            ["-mega", "p1a", "gardevoir"]
        )
        malformed_targets.append(("incomplete-mega-event", incomplete_mega))

        padded_hitcount = copy.deepcopy(deterministic_view)
        padded_hitcount["public_event_delta"]["events"].append(
            ["-hitcount", "p1a", "01"]
        )
        malformed_targets.append(("padded-hitcount", padded_hitcount))

        nonfinite_hp = copy.deepcopy(deterministic_view)
        nonfinite_hp["player"]["team"][0]["hp_percent"] = float("nan")
        malformed_targets.append(("nonfinite-hp", nonfinite_hp))

        unknown_boost = copy.deepcopy(deterministic_view)
        active_detail = next(
            (
                pokemon
                for pokemon in unknown_boost["player"]["active_details"]
                if isinstance(pokemon, dict)
            ),
            None,
        )
        if active_detail is None:
            raise SystemExit(
                "ERROR: reachability smoke has no active detail for boost validation"
            )
        active_detail["boosts"]["future-stat"] = 900
        malformed_targets.append(("unknown-boost-dimension", unknown_boost))

        partial_move = copy.deepcopy(deterministic_view)
        active_request = partial_move.get("request")
        if (
            not isinstance(active_request, dict)
            or not isinstance(active_request.get("active"), list)
        ):
            raise SystemExit(
                "ERROR: reachability smoke expected a move request after zero-draw turn"
            )
        move_entry = next(
            (
                move
                for slot in active_request["active"]
                if isinstance(slot, dict)
                for move in slot.get("moves", [])
                if isinstance(move, dict)
                and {"pp", "maxpp", "target", "disabled"}.issubset(move)
            ),
            None,
        )
        if move_entry is not None:
            move_entry.pop("pp")
            malformed_targets.append(("partial-move-variant", partial_move))

        impossible_hp_condition = copy.deepcopy(deterministic_view)
        impossible_hp_condition["public_event_delta"]["events"].append(
            ["-damage", "p1a", "101/100"]
        )
        malformed_targets.append(
            ("impossible-hp-condition", impossible_hp_condition)
        )

        overlong_crit = copy.deepcopy(deterministic_view)
        overlong_crit["public_event_delta"]["events"].append(
            ["-crit", "p1a", "extra"]
        )
        malformed_targets.append(("overlong-crit-event", overlong_crit))

        called_without_provenance = copy.deepcopy(deterministic_view)
        called_without_provenance["public_execution_delta"] = {
            "turn": max(1, deterministic_view["turn"]),
            "actions": [
                {
                    "side": "player",
                    "slot": 1,
                    "outcome": "executed",
                    "move": "tackle",
                    "source": "called",
                    "provenance": [],
                    "effects": [],
                }
            ],
        }
        malformed_targets.append(
            ("called-without-provenance", called_without_provenance)
        )

        bad_request_condition = copy.deepcopy(deterministic_view)
        bad_request = bad_request_condition.get("request")
        bad_side = bad_request.get("side") if isinstance(bad_request, dict) else None
        bad_roster = bad_side.get("pokemon") if isinstance(bad_side, dict) else None
        if isinstance(bad_roster, list) and bad_roster:
            bad_roster[0]["condition"] = "garbage"
            malformed_targets.append(
                ("malformed-request-condition", bad_request_condition)
            )

        for label, malformed_target in malformed_targets:
            malformed_result = evaluate_deterministic_public_transition(
                worker,
                state=state,
                side="p2",
                step=PublicReachabilityStep(
                    p1_choice=deterministic_p1,
                    p2_choice=deterministic_p2,
                    expected_public_view=malformed_target,
                ),
            )
            if malformed_result.status is not ReachabilityStatus.UNSUPPORTED:
                raise SystemExit(
                    "ERROR: malformed reachability evidence became authoritative "
                    f"({label}): {malformed_result}"
                )
            if malformed_result.conclusive:
                raise SystemExit(
                    "ERROR: malformed reachability evidence became conclusive "
                    f"({label})"
                )

        supported_shape_unsupported = copy.deepcopy(deterministic_view)
        supported_shape_unsupported["public_event_delta"]["unsupported"] = [
            "future-mechanic"
        ]
        unsupported_result = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p2",
            step=PublicReachabilityStep(
                p1_choice=deterministic_p1,
                p2_choice=deterministic_p2,
                expected_public_view=supported_shape_unsupported,
            ),
        )
        if unsupported_result.status is not ReachabilityStatus.UNSUPPORTED:
            raise SystemExit(
                "ERROR: valid unsupported evidence did not fail closed: "
                f"{unsupported_result}"
            )
        deterministic_witness = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p2",
            step=PublicReachabilityStep(
                p1_choice=deterministic_p1,
                p2_choice=deterministic_p2,
                expected_public_view=deterministic_view,
            ),
        )
        if deterministic_witness.status is not ReachabilityStatus.WITNESSED:
            raise SystemExit(
                "ERROR: zero-draw exact outcome was not witnessed: "
                f"{deterministic_witness}"
            )

        impossible_view = copy.deepcopy(deterministic_view)
        impossible_view["winner"] = "__impossible_zero_draw_winner__"
        deterministic_disproof = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p2",
            step=PublicReachabilityStep(
                p1_choice=deterministic_p1,
                p2_choice=deterministic_p2,
                expected_public_view=impossible_view,
            ),
        )
        if (
            deterministic_disproof.status
            is not ReachabilityStatus.EXHAUSTIVELY_DISPROVED
        ):
            raise SystemExit(
                "ERROR: zero-draw mismatch did not produce exhaustive disproof: "
                f"{deterministic_disproof}"
            )

        randomized_target = copy.deepcopy(target)
        randomized_target["winner"] = "__impossible_randomized_winner__"
        randomized_mismatch = evaluate_deterministic_public_transition(
            worker,
            state=state,
            side="p2",
            step=PublicReachabilityStep(
                p1_choice=P1_CHOICE,
                p2_choice=P2_CHOICE,
                expected_public_view=randomized_target,
                rng_seeds=(WITNESS_SEED,),
            ),
        )
        if randomized_mismatch.status is not ReachabilityStatus.UNRESOLVED:
            raise SystemExit(
                "ERROR: randomized mismatch gained negative authority: "
                f"{randomized_mismatch}"
            )

        _assert_real_producer_variants(worker)

        print("Pinned Showdown reachability authority smoke")
        print(f"Witness status: {witnessed.status.value}")
        print(f"Witness branches examined: {witnessed.coverage.outcomes_examined}")
        print(f"Non-witness seed: {miss_seed}")
        print(f"Non-witness status: {missed.status.value}")
        print(
            "Zero-draw commands: "
            f"{deterministic_p1!r} / {deterministic_p2!r}"
        )
        print(
            "Zero-draw disproof status: "
            f"{deterministic_disproof.status.value}"
        )
        print(
            "Randomized mismatch status: "
            f"{randomized_mismatch.status.value}"
        )
        print(
            "RESULT: zero-draw mismatches can be disproved; "
            "randomized misses stay unresolved"
        )


if __name__ == "__main__":
    main()
