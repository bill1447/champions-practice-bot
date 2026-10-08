from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from champions_practice.belief_controller import (
    BeliefRecoveryDiagnostic,
    SealedTurnState,
)
from champions_practice.observation_beliefs import StructuralMismatchExample
from champions_practice.strength_league import LeagueConfig
from champions_practice.transition_drift_probe import (
    _classification,
    _mechanics_projection,
    _team_signature,
    run_transition_drift_probe,
)


def _state(*, prng: str, hp: int = 100, turn: int = 7) -> dict:
    return {
        "turn": turn,
        "prng": {"seed": prng},
        "field": {"weather": "", "terrain": "grassyterrain"},
        "sides": [
            {
                "sideConditions": {},
                "pokemon": [
                    {
                        "set": {
                            "species": "Gardevoir",
                            "item": "Gardevoirite",
                            "ability": "Trace",
                            "moves": ["Protect", "Mystical Fire"],
                        },
                        "position": 0,
                        "hp": hp,
                        "maxhp": 100,
                        "status": "",
                        "boosts": {},
                        "volatiles": {},
                        "item": "gardevoirite",
                        "ability": "trace",
                    }
                ],
            },
            {
                "sideConditions": {},
                "pokemon": [
                    {
                        "set": {
                            "species": "Rillaboom",
                            "item": "Sitrus Berry",
                            "ability": "Grassy Surge",
                            "moves": ["Wood Hammer", "Protect"],
                        },
                        "position": 0,
                        "hp": 100,
                        "maxhp": 100,
                        "status": "",
                        "boosts": {},
                        "volatiles": {},
                        "item": "sitrusberry",
                        "ability": "grassysurge",
                    }
                ],
            },
        ],
    }


def _diagnostic() -> BeliefRecoveryDiagnostic:
    return BeliefRecoveryDiagnostic(
        reason="zero-sampled-match",
        observation_turn=8,
        observation_sha256="a" * 64,
        observed_opponent_actions=(),
        particles_before=1,
        worlds_before=1,
        generated_branches=368,
        sampled_matches=0,
        stochastic_only_mismatches=0,
        structural_mismatches=32,
        structural_mismatch_paths=(("$.player.active_details[1].hp", 29),),
        structural_mismatch_worlds=(("world-3", 32),),
        structural_mismatch_examples=(
            StructuralMismatchExample(
                world_id="world-3",
                path="$.player.active_details[1].hp",
                actual=134,
                simulated=131,
                opponent_choice="move protect, move woodhammer +2",
                rng_seed="seed",
            ),
        ),
        finite_reachability_witnesses=0,
        finite_reachability_disproofs=0,
        finite_reachability_unresolved=1,
        finite_reachability_leaves=208,
        sampled_matched_worlds=0,
        sampled_unresolved_worlds=1,
        exhaustively_excluded_worlds=0,
        recovery_candidates_remaining=1,
        recovery_worlds_remaining=1,
    )


def test_team_signature_ignores_party_order_but_not_hidden_set() -> None:
    first = _state(prng="one")
    second = deepcopy(first)
    second["sides"][0]["pokemon"].reverse()

    assert _team_signature(first, 0) == _team_signature(second, 0)

    second["sides"][0]["pokemon"][0]["set"]["item"] = "Leftovers"
    assert _team_signature(first, 0) != _team_signature(second, 0)


def test_mechanics_projection_excludes_prng_but_tracks_protect_state() -> None:
    first = _state(prng="one")
    second = _state(prng="two")

    first["sides"][0]["pokemon"][0]["volatiles"] = {"stall": {"counter": 2}}
    second["sides"][0]["pokemon"][0]["volatiles"] = {"stall": {"counter": 2}}

    assert _mechanics_projection(first) == _mechanics_projection(second)

    second["sides"][0]["pokemon"][0]["volatiles"]["stall"]["counter"] = 3
    assert _mechanics_projection(first) != _mechanics_projection(second)


def test_classification_keeps_rng_miss_separate_from_state_drift() -> None:
    assert (
        _classification(
            oracle_replay_matches=True,
            candidates=[
                {
                    "oracle_prng_replay_matches_public": True,
                    "mechanics_diff_count": 0,
                }
            ],
        )
        == "rng-search-miss"
    )
    assert (
        _classification(
            oracle_replay_matches=True,
            candidates=[
                {
                    "oracle_prng_replay_matches_public": False,
                    "mechanics_diff_count": 2,
                }
            ],
        )
        == "retained-state-drift-or-non-prng-randomness"
    )


def test_probe_reads_oracle_only_after_ai_action_is_sealed(
    monkeypatch,
    tmp_path,
) -> None:
    expected_view = {
        "turn": 8,
        "phase": "move",
        "player": {"active": [{"species": "Rillaboom"}]},
        "opponent": {"active": [{"species": "Gardevoir"}]},
    }
    human_view = {
        "turn": 8,
        "phase": "move",
        "player": {"active": [{"species": "Gardevoir"}]},
        "opponent": {"active": [{"species": "Rillaboom"}]},
    }
    oracle_pre = _state(prng="oracle", turn=7)
    particle_state = _state(prng="particle", turn=7)
    oracle_post = _state(prng="after", hp=82, turn=8)
    writes = []
    events = []

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            self.after = False
            events.append("worker-created")

        def session_snapshot(self, session_id):
            assert session_id == "session-1"
            events.append("oracle-snapshot")
            return {
                "state": deepcopy(oracle_post if self.after else oracle_pre),
                "summary": {},
            }

        def session_view(self, session_id, *, side):
            assert session_id == "session-1"
            assert side == "p2"
            return {"view": deepcopy(expected_view)}

        def branch_many(self, *, state, branches):
            assert len(branches) == 1
                {
                    "state": deepcopy(oracle_post),
                    "view": deepcopy(expected_view),
                }
            ]

    particle = SimpleNamespace(
        state=particle_state,
        world_id="world-3",
        history_id="rng-1",
        weight=1.0,
    )

    class FakeCoordinator:
        def __init__(self, worker, **kwargs):
            self.worker = worker
            self.turn_state = SealedTurnState.NEW
            self.preview_done = False

        def start(self, **kwargs):
            self.turn_state = SealedTurnState.PREVIEW

        def human_legal_choices(self):
            if not self.preview_done:
                return ["team 2, 1, 3, 5"]
            return ["move protect, move woodhammer +2"]

        def submit_preview(self, *, human_choice, ai_choice):
            self.preview_done = True
            self.turn_state = SealedTurnState.IDLE

        def lock_ai_action(self):
            events.append("ai-sealed")
            self.turn_state = SealedTurnState.LOCKED
            return SimpleNamespace(token="sealed")

        def _engine_snapshot(self):
            return SimpleNamespace(particles=(particle,))

        def _require_session(self):
            return "session-1"

        def commit_human_action(self, *, token, human_choice):
            assert events.index("ai-sealed") < events.index("oracle-snapshot")
            self.worker.after = True
            self.turn_state = SealedTurnState.RESOLVED
            return SimpleNamespace(
                recovery_diagnostic=_diagnostic(),
                collapse_diagnostic=None,
                decision=SimpleNamespace(
                    choice="move protect, move woodhammer +2",
                    mode="belief-search",
                ),
                public_view=deepcopy(human_view),
                terminal=False,
            )

        def close(self):
            self.turn_state = SealedTurnState.CLOSED

    monkeypatch.setattr(
        "champions_practice.transition_drift_probe.ShowdownSearchWorker",
        FakeWorker,
    )
    monkeypatch.setattr(
        "champions_practice.transition_drift_probe._BeliefBattleCoordinator",
        FakeCoordinator,
    )
    monkeypatch.setattr(
        "champions_practice.transition_drift_probe._git_commit",
        lambda root: "a" * 40,
    )
    monkeypatch.setattr(
        "champions_practice.transition_drift_probe._showdown_revision",
        lambda root: "b" * 40,
    )
    monkeypatch.setattr(
        "champions_practice.transition_drift_probe._atomic_write_json",
        lambda path, payload: writes.append((path, payload)),
    )

    report = run_transition_drift_probe(
        config=LeagueConfig(battles=1, max_decisions=4),
        game_index=1,
        project_root=tmp_path,
    )

    assert report["capture_boundary"] == "after-ai-seal-before-human-submit"
    assert report["oracle_capture_after_ai_seal"] is True
    assert report["oracle_replay_matches_public"] is True
    assert report["classification"] == "rng-search-miss"
    assert report["conditioning_public_view"] == expected_view
    assert report["human_public_view"] == human_view
    assert report["true_world_candidate_count"] == 1
    candidate = report["true_world_candidates"][0]
    assert candidate["mechanics_diff_count"] == 0
    assert candidate["oracle_prng_replay_matches_public"] is True
    assert candidate["oracle_prng_keys_copied"] == ("prng",)
    assert len(writes) == 2
