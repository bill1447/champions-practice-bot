"""Diagnose whether a structural collapse is RNG-only or retained-state drift."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from champions_practice.belief_controller import (
    SealedTurnState,
    _BeliefBattleCoordinator,
    _public_diff_paths,
    _value_at_path,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    demo_public_priors,
)
from champions_practice.observation_beliefs import public_observation_signature
from champions_practice.search_worker import ShowdownSearchWorker
from champions_practice.strength_league import (
    FIXTURE_ID,
    LeagueConfig,
    StrengthLeagueError,
    _atomic_write_json,
    _baseline_choice,
    _git_commit,
    _particle_seed,
    _resolve_preview_choice,
    _showdown_revision,
    _sodium_seed,
)


PROBE_SCHEMA = "transition-state-drift-probe-v2"

_BATTLE_MECHANICS_KEYS = (
    "turn",
    "midTurn",
    "requestState",
    "field",
    "queue",
)
_SIDE_MECHANICS_KEYS = (
    "sideConditions",
    "slotConditions",
)
_POKEMON_MECHANICS_KEYS = (
    "position",
    "active",
    "fainted",
    "hp",
    "maxhp",
    "status",
    "statusState",
    "boosts",
    "volatiles",
    "item",
    "itemState",
    "ability",
    "abilityState",
    "baseAbility",
    "species",
    "details",
    "transformed",
    "teraType",
    "terastallized",
    "lastMove",
    "moveThisTurn",
    "moveLastTurnResult",
    "usedItemThisTurn",
    "attackedBy",
    "speed",
)


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _side(state: dict[str, Any], side_index: int) -> dict[str, Any] | None:
    sides = state.get("sides")
    if not isinstance(sides, list):
        return None
    if side_index < 0 or side_index >= len(sides):
        return None
    side = sides[side_index]
    return side if isinstance(side, dict) else None


def _team_signature(state: dict[str, Any], side_index: int) -> str | None:
    side = _side(state, side_index)
    if side is None:
        return None
    pokemon = side.get("pokemon")
    if not isinstance(pokemon, list):
        return None

    member_sets: list[str] = []
    for member in pokemon:
        if not isinstance(member, dict):
            return None
        set_data = member.get("set")
        if not isinstance(set_data, dict):
            return None
        member_sets.append(_stable_json(set_data))
    return hashlib.sha256(
        "\n".join(sorted(member_sets)).encode("utf-8")
    ).hexdigest()


def _mechanics_projection(state: dict[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for key in _BATTLE_MECHANICS_KEYS:
        if key in state:
            projection[key] = deepcopy(state[key])

    sides_value = state.get("sides")
    projected_sides: list[dict[str, Any]] = []
    if isinstance(sides_value, list):
        for raw_side in sides_value:
            if not isinstance(raw_side, dict):
                projected_sides.append({})
                continue
            side_projection: dict[str, Any] = {}
            for key in _SIDE_MECHANICS_KEYS:
                if key in raw_side:
                    side_projection[key] = deepcopy(raw_side[key])

            raw_pokemon = raw_side.get("pokemon")
            projected_pokemon: list[dict[str, Any]] = []
            if isinstance(raw_pokemon, list):
                for raw_member in raw_pokemon:
                    if not isinstance(raw_member, dict):
                        projected_pokemon.append({})
                        continue
                    member_projection = {
                        key: deepcopy(raw_member[key])
                        for key in _POKEMON_MECHANICS_KEYS
                        if key in raw_member
                    }
                    set_data = raw_member.get("set")
                    if isinstance(set_data, dict):
                        member_projection["set_species"] = set_data.get("species")
                    projected_pokemon.append(member_projection)
            side_projection["pokemon"] = projected_pokemon
            projected_sides.append(side_projection)
    projection["sides"] = projected_sides
    return projection


def _diff_values(
    actual: Any,
    simulated: Any,
    *,
    path: str = "$",
    limit: int = 64,
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []

    def visit(left: Any, right: Any, current_path: str) -> None:
        if len(differences) >= limit:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                visit(
                    left.get(key),
                    right.get(key),
                    f"{current_path}.{key}",
                )
            return
        if isinstance(left, list) and isinstance(right, list):
            max_length = max(len(left), len(right))
            for index in range(max_length):
                left_value = left[index] if index < len(left) else None
                right_value = right[index] if index < len(right) else None
                visit(
                    left_value,
                    right_value,
                    f"{current_path}[{index}]",
                )
            return
        if left != right:
            differences.append(
                {
                    "path": current_path,
                    "actual": left,
                    "particle": right,
                }
            )

    visit(actual, simulated, path)
    return differences


def _copy_oracle_prng(
    particle_state: dict[str, Any],
    oracle_state: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    copied = deepcopy(particle_state)
    keys = tuple(
        sorted(
            key
            for key in oracle_state
            if "prng" in key.lower()
        )
    )
    for key in keys:
        copied[key] = deepcopy(oracle_state[key])
    return copied, keys


def _previews_from_state(state: dict[str, Any]) -> dict[str, list[str]]:
    previews: dict[str, list[str]] = {"p1": [], "p2": []}
    for side_index, side_id in enumerate(("p1", "p2")):
        side = _side(state, side_index)
        pokemon = side.get("pokemon") if isinstance(side, dict) else None
        if not isinstance(pokemon, list):
            continue
        for member in pokemon:
            if not isinstance(member, dict):
                continue
            set_data = member.get("set")
            species = set_data.get("species") if isinstance(set_data, dict) else None
            if isinstance(species, str) and species:
                previews[side_id].append(species)
    return previews


def _replay(
    worker: ShowdownSearchWorker,
    *,
    state: dict[str, Any],
    p1_choice: str,
    p2_choice: str,
    previews: dict[str, list[str]],
) -> dict[str, Any]:
    branches = worker.branch_many(
        state=state,
        branches=[
            {
                "p1_choice": p1_choice,
                "p2_choice": p2_choice,
                "include_state": True,
                "view_side": "p2",
                "previews": previews,
            }
        ],
    )
    if len(branches) != 1:
        raise RuntimeError("diagnostic replay returned an invalid branch count")
    branch = branches[0]
    replay_state = branch.get("state")
    replay_view = branch.get("view")
    if not isinstance(replay_state, dict) or not isinstance(replay_view, dict):
        raise RuntimeError("diagnostic replay omitted state or public view")
    return branch


def _public_mismatch_examples(
    actual_view: dict[str, Any],
    simulated_view: dict[str, Any],
    *,
    limit: int = 16,
) -> list[dict[str, Any]]:
    paths = _public_diff_paths(actual_view, simulated_view)
    return [
        {
            "path": path,
            "actual": _value_at_path(actual_view, path),
            "simulated": _value_at_path(simulated_view, path),
        }
        for path in paths[:limit]
    ]


def _classification(
    *,
    oracle_replay_matches: bool,
    candidates: list[dict[str, Any]],
) -> str:
    if not oracle_replay_matches:
        return "probe-invalid-oracle-replay-mismatch"
    if not candidates:
        return "true-world-not-retained"
    for candidate in candidates:
        if (
            candidate["oracle_prng_replay_matches_public"]
            and candidate["mechanics_diff_count"] == 0
        ):
            return "rng-search-miss"
    if any(
        candidate["oracle_prng_replay_matches_public"]
        for candidate in candidates
    ):
        return "rng-compatible-with-noncausal-state-differences"
    return "retained-state-drift-or-non-prng-randomness"


def _probe_id(
    *,
    git_commit: str,
    showdown_revision: str,
    config: LeagueConfig,
    game_index: int,
) -> str:
    payload = {
        "schema": PROBE_SCHEMA,
        "fixture_id": FIXTURE_ID,
        "git_commit": git_commit,
        "showdown_revision": showdown_revision,
        "config": asdict(config),
        "game_index": game_index,
    }
    return _sha256_json(payload)[:20]


def run_transition_drift_probe(
    *,
    config: LeagueConfig | None = None,
    game_index: int = 1,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen fixture until the first structural conditioning collapse."""
    if game_index < 0:
        raise ValueError("game_index must be non-negative")
    config = config or LeagueConfig(battles=1, max_decisions=16)
    root = (
        Path(project_root).expanduser().resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    git_commit = _git_commit(root)
    showdown_revision = _showdown_revision(root)
    session_seed = _sodium_seed(config.seed, game_index)
    particle_seed = _particle_seed(config.seed, game_index)

    worker = ShowdownSearchWorker(
        root,
        startup_timeout_seconds=config.worker_startup_timeout_seconds,
    )
    coordinator = _BeliefBattleCoordinator(
        worker,
        battle_format=CHAMPIONS_FORMAT,
        ai_team=DEMO_AI_TEAM,
        opponent_priors=demo_public_priors(),
        world_limit=config.world_limit,
        particles_per_world=config.particles_per_world,
        max_particles=config.max_particles,
        candidate_limit=config.candidate_limit,
        response_limit=config.response_limit,
        strategic_plan_limit=config.strategic_plan_limit,
        strategic_candidate_limit=config.strategic_candidate_limit,
        strategic_response_limit=config.strategic_response_limit,
        decision_budget_seconds=config.decision_budget_seconds,
        conditioning_budget_seconds=config.conditioning_budget_seconds,
        particle_seed=particle_seed,
    )

    try:
        coordinator.start(
            opponent_team=DEMO_HUMAN_TEAM,
            p1_name="Drift Baseline",
            p2_name="Drift Bot",
            session_seed=session_seed,
        )
        preview_choices = tuple(coordinator.human_legal_choices())
        baseline_preview = _resolve_preview_choice(
            preview_choices,
            DEMO_AI_PREVIEW_CHOICE,
        )
        coordinator.submit_preview(
            human_choice=baseline_preview,
            ai_choice=DEMO_AI_PREVIEW_CHOICE,
        )

        for decision_index in range(config.max_decisions):
            choices = tuple(coordinator.human_legal_choices())
            if not choices:
                raise StrengthLeagueError(
                    "transition-drift probe exposed no legal baseline choices"
                )
            human_choice = _baseline_choice(choices)
            ready = coordinator.lock_ai_action()

            if coordinator.turn_state is not SealedTurnState.LOCKED:
                raise RuntimeError(
                    "oracle capture attempted before the AI decision was sealed"
                )

            engine_snapshot = coordinator._engine_snapshot()
            session_id = coordinator._require_session()
            oracle_pre_result = worker.session_snapshot(session_id)
            oracle_pre_state = oracle_pre_result.get("state")
            if not isinstance(oracle_pre_state, dict):
                raise RuntimeError("oracle pre-turn snapshot omitted exact state")

            result = coordinator.commit_human_action(
                token=ready.token,
                human_choice=human_choice,
            )
            diagnostic = result.recovery_diagnostic
            if diagnostic is None or diagnostic.structural_mismatches <= 0:
                if result.terminal:
                    break
                continue

            oracle_post_result = worker.session_snapshot(session_id)
            oracle_post_state = oracle_post_result.get("state")
            if not isinstance(oracle_post_state, dict):
                raise RuntimeError("oracle post-turn snapshot omitted exact state")
            conditioning_view_result = worker.session_view(
                session_id,
                side="p2",
            )
            conditioning_public_view = conditioning_view_result.get("view")
            if not isinstance(conditioning_public_view, dict):
                raise RuntimeError(
                    "oracle post-turn p2 view omitted conditioning observation"
                )

            previews = _previews_from_state(oracle_pre_state)
            oracle_replay = _replay(
                worker,
                state=oracle_pre_state,
                p1_choice=human_choice,
                p2_choice=result.decision.choice,
                previews=previews,
            )
            oracle_replay_view = oracle_replay["view"]
            oracle_replay_state = oracle_replay["state"]
            actual_signature = public_observation_signature(
                conditioning_public_view
            )
            oracle_replay_matches = (
                public_observation_signature(oracle_replay_view)
                == actual_signature
            )

            true_team_signature = _team_signature(oracle_pre_state, 0)
            oracle_projection = _mechanics_projection(oracle_pre_state)
            candidates: list[dict[str, Any]] = []
            for particle in engine_snapshot.particles:
                if _team_signature(particle.state, 0) != true_team_signature:
                    continue

                particle_projection = _mechanics_projection(particle.state)
                mechanics_differences = _diff_values(
                    oracle_projection,
                    particle_projection,
                )
                transplanted_state, prng_keys = _copy_oracle_prng(
                    particle.state,
                    oracle_pre_state,
                )
                replay = _replay(
                    worker,
                    state=transplanted_state,
                    p1_choice=human_choice,
                    p2_choice=result.decision.choice,
                    previews=previews,
                )
                replay_matches = (
                    public_observation_signature(replay["view"])
                    == actual_signature
                )
                candidates.append(
                    {
                        "world_id": particle.world_id,
                        "history_id": particle.history_id,
                        "weight": particle.weight,
                        "state_sha256": _sha256_json(particle.state),
                        "mechanics_projection": particle_projection,
                        "mechanics_diff_count": len(mechanics_differences),
                        "mechanics_differences": mechanics_differences,
                        "oracle_prng_keys_copied": prng_keys,
                        "oracle_prng_replay_matches_public": replay_matches,
                        "oracle_prng_replay_mismatches": (
                            []
                            if replay_matches
                            else _public_mismatch_examples(
                                conditioning_public_view,
                                replay["view"],
                            )
                        ),
                    }
                )

            classification = _classification(
                oracle_replay_matches=oracle_replay_matches,
                candidates=candidates,
            )
            probe_id = _probe_id(
                git_commit=git_commit,
                showdown_revision=showdown_revision,
                config=config,
                game_index=game_index,
            )
            report = {
                "schema": PROBE_SCHEMA,
                "probe_id": probe_id,
                "fixture_id": FIXTURE_ID,
                "format_id": CHAMPIONS_FORMAT,
                "git_commit": git_commit,
                "showdown_revision": showdown_revision,
                "game_index": game_index,
                "decision_index": decision_index,
                "session_seed": session_seed,
                "particle_seed": particle_seed,
                "human_choice": human_choice,
                "ai_choice": result.decision.choice,
                "decision_mode": result.decision.mode,
                "capture_boundary": "after-ai-seal-before-human-submit",
                "oracle_capture_after_ai_seal": True,
                "classification": classification,
                "true_team_signature": true_team_signature,
                "retained_particle_count": len(engine_snapshot.particles),
                "true_world_candidate_count": len(candidates),
                "oracle_pre_state_sha256": _sha256_json(oracle_pre_state),
                "oracle_post_state_sha256": _sha256_json(oracle_post_state),
                "oracle_pre_mechanics": oracle_projection,
                "oracle_replay_matches_public": oracle_replay_matches,
                "oracle_replay_matches_post_state": (
                    _sha256_json(oracle_replay_state)
                    == _sha256_json(oracle_post_state)
                ),
                "oracle_replay_mismatches": (
                    []
                    if oracle_replay_matches
                    else _public_mismatch_examples(
                        conditioning_public_view,
                        oracle_replay_view,
                    )
                ),
                "true_world_candidates": candidates,
                "conditioning_public_view": conditioning_public_view,
                "human_public_view": result.public_view,
                "recovery_diagnostic": asdict(diagnostic),
                "collapse_diagnostic": (
                    asdict(result.collapse_diagnostic)
                    if result.collapse_diagnostic is not None
                    else None
                ),
                "config": asdict(config),
            }
            base = root / "runs" / "transition-drift"
            _atomic_write_json(base / probe_id / "report.json", report)
            _atomic_write_json(base / "latest-report.json", report)
            return report

    finally:
        coordinator.close()

    raise StrengthLeagueError(
        "no structural belief-conditioning collapse was reproduced within "
        f"{config.max_decisions} decisions"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-index", type=int, default=1)
    parser.add_argument("--max-decisions", type=int, default=16)
    parser.add_argument("--decision-budget-seconds", type=float, default=8.0)
    parser.add_argument("--conditioning-budget-seconds", type=float, default=8.0)
    parser.add_argument("--worker-startup-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=15601)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    config = LeagueConfig(
        battles=1,
        max_decisions=args.max_decisions,
        decision_budget_seconds=args.decision_budget_seconds,
        conditioning_budget_seconds=args.conditioning_budget_seconds,
        worker_startup_timeout_seconds=args.worker_startup_timeout_seconds,
        seed=args.seed,
    )
    try:
        report = run_transition_drift_probe(
            config=config,
            game_index=args.game_index,
        )
    except (StrengthLeagueError, RuntimeError, ValueError, OSError) as error:
        raise SystemExit(f"ERROR: {error}") from error

    diagnostic = report["recovery_diagnostic"]
    print(f"Probe:          {report['probe_id']}")
    print(f"Game:           {report['game_index']}")
    print(f"Decision:       {report['decision_index']}")
    print(f"Reason:         {diagnostic['reason']}")
    print(f"Human:          {report['human_choice']}")
    print(f"AI:             {report['ai_choice']}")
    print(f"Classification: {report['classification']}")
    print(
        "True-world:     "
        f"{report['true_world_candidate_count']} / "
        f"{report['retained_particle_count']} retained particles"
    )
    print(
        "Oracle replay:  "
        f"public={report['oracle_replay_matches_public']} | "
        f"state={report['oracle_replay_matches_post_state']}"
    )
    for candidate in report["true_world_candidates"]:
        print(
            "Candidate:      "
            f"{candidate['world_id']} {candidate['history_id']} | "
            f"mechanics diffs {candidate['mechanics_diff_count']} | "
            "oracle-PRNG replay "
            f"{candidate['oracle_prng_replay_matches_public']}"
        )
    report_path = (
        Path(__file__).resolve().parents[2]
        / "runs"
        / "transition-drift"
        / "latest-report.json"
    )
    print(f"Report:         {report_path}")


if __name__ == "__main__":
    main()
