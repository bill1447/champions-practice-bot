from __future__ import annotations

from types import SimpleNamespace

from champions_practice.belief_controller import (
    BeliefCollapseDiagnostic,
    BeliefRecoveryDiagnostic,
)
from champions_practice.observation_beliefs import StructuralMismatchExample
from champions_practice.strength_league import LeagueConfig
from champions_practice.structural_collapse_probe import (
    _probe_id,
    run_structural_collapse_probe,
)


def _collapse() -> BeliefCollapseDiagnostic:
    return BeliefCollapseDiagnostic(
        summary="exact-match-found-with-extra-rng",
        elapsed_seconds=0.25,
        budget_exhausted=False,
        generated_branches=12,
        exact_matches=1,
        worlds_tested=8,
        legal_worlds=8,
        illegal_worlds=0,
        common_mismatch_paths=(("$.opponent.active[0].status", 11),),
    )


def _diagnostic() -> BeliefRecoveryDiagnostic:
    return BeliefRecoveryDiagnostic(
        reason="zero-sampled-match",
        observation_turn=3,
        observation_sha256="a" * 64,
        observed_opponent_actions=(),
        particles_before=8,
        worlds_before=8,
        generated_branches=384,
        sampled_matches=0,
        stochastic_only_mismatches=0,
        structural_mismatches=384,
        structural_mismatch_paths=(("$.request.active[0]", 384),),
        structural_mismatch_worlds=(("world-a", 48),),
        structural_mismatch_examples=(
            StructuralMismatchExample(
                world_id="world-a",
                path="$.request.active[0]",
                actual={"moves": ["protect"]},
                simulated={"moves": ["psychic"]},
                opponent_choice="move protect",
                rng_seed="seed",
            ),
        ),
        sampled_matched_worlds=0,
        sampled_unresolved_worlds=8,
        exhaustively_excluded_worlds=0,
        recovery_candidates_remaining=8,
        recovery_worlds_remaining=8,
    )


def test_probe_id_is_deterministic_and_game_specific() -> None:
    config = LeagueConfig(battles=1, max_decisions=16)
    first = _probe_id(
        git_commit="a" * 40,
        showdown_revision="b" * 40,
        config=config,
        game_index=0,
    )
    second = _probe_id(
        git_commit="a" * 40,
        showdown_revision="b" * 40,
        config=config,
        game_index=0,
    )
    other_game = _probe_id(
        git_commit="a" * 40,
        showdown_revision="b" * 40,
        config=config,
        game_index=1,
    )

    assert first == second
    assert first != other_game
    assert len(first) == 20


def test_probe_stops_and_persists_first_structural_collapse(
    monkeypatch,
    tmp_path,
) -> None:
    writes = []

    class FakeBattle:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.legal_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def start(self, **kwargs):
            self.start_kwargs = kwargs

        def legal_human_choices(self):
            self.legal_calls += 1
            if self.legal_calls == 1:
                return ("team 2, 1, 3, 5",)
            return ("move baseline",)

        def commit_preview(self, *, human_choice):
            assert human_choice == "team 2, 1, 3, 5"

        def lock_ai_action(self):
            return SimpleNamespace(token="sealed")

        def commit_human_action(self, *, token, human_choice):
            assert token == "sealed"
            assert human_choice == "move baseline"
            return SimpleNamespace(
                recovery_diagnostic=_diagnostic(),
                collapse_diagnostic=_collapse(),
                decision=SimpleNamespace(
                    choice="move protect, move protect",
                    mode="belief-search",
                ),
                public_view={"turn": 3},
                terminal=False,
            )

    monkeypatch.setattr(
        "champions_practice.structural_collapse_probe.SealedBattleFacade",
        FakeBattle,
    )
    monkeypatch.setattr(
        "champions_practice.structural_collapse_probe._baseline_choice",
        lambda choices: choices[0],
    )
    monkeypatch.setattr(
        "champions_practice.structural_collapse_probe._git_commit",
        lambda root: "a" * 40,
    )
    monkeypatch.setattr(
        "champions_practice.structural_collapse_probe._showdown_revision",
        lambda root: "b" * 40,
    )
    monkeypatch.setattr(
        "champions_practice.structural_collapse_probe._atomic_write_json",
        lambda path, payload: writes.append((path, payload)),
    )

    report = run_structural_collapse_probe(
        config=LeagueConfig(battles=1, max_decisions=4),
        game_index=0,
        project_root=tmp_path,
    )

    assert report["decision_index"] == 0
    assert report["recovery_diagnostic"]["structural_mismatches"] == 384
    assert report["recovery_diagnostic"]["structural_mismatch_paths"] == (
        ("$.request.active[0]", 384),
    )
    assert report["collapse_diagnostic"]["summary"] == (
        "exact-match-found-with-extra-rng"
    )
    assert report["collapse_diagnostic"]["exact_matches"] == 1
    assert len(writes) == 2
    assert writes[0][0].name == "report.json"
    assert writes[1][0].name == "latest-report.json"
