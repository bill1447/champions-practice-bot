from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from champions_practice.replay_corpus import DEFAULT_FORMAT, initialize_layout
from champions_practice.replay_semantic_audit import (
    SEMANTIC_AUDIT_SCHEMA,
    SEMANTIC_POLICY_SCHEMA,
)
from champions_practice.semantic_policy_diagnostics import (
    compare_training_runs,
    evaluate_saved_training,
    format_comparison_table,
)
from champions_practice.semantic_policy_registry import (
    register_dataset_alias,
    register_training_alias,
)
from champions_practice.semantic_policy_train import (
    MODEL_SCHEMA,
    TRAINING_REPORT_SCHEMA,
    SemanticPolicyTrainingError,
    TrainingConfig,
    train_semantic_policy,
    training_status,
)


def _active(species: str) -> dict:
    return {
        "base_species": species,
        "visible_species": species,
        "hp_percent": 100.0,
        "status": None,
        "fainted": False,
        "boosts": {},
    }


def _state(turn: int) -> dict:
    return {
        "schema": "showdown-replay-public-state-v1",
        "turn": turn,
        "gametype": "doubles",
        "field": {"weather": None, "conditions": []},
        "sides": {
            "p1": {
                "name": "Alice",
                "preview_species": ["Indeedee-F", "Sneasler", "Rillaboom"],
                "active": [_active("Indeedee-F"), _active("Sneasler")],
                "side_conditions": [],
                "revealed": [],
            },
            "p2": {
                "name": "Bob",
                "preview_species": ["Pelipper", "Archaludon", "Rillaboom"],
                "active": [_active("Pelipper"), _active("Archaludon")],
                "side_conditions": [],
                "revealed": [],
            },
        },
    }


def _row(index: int, *, split: str) -> dict:
    move_a = f"move{index % 20}"
    move_b = f"coverage{index % 20}"
    rating_band = (
        "1600-1799"
        if index % 5 == 0
        else "1400-1599"
        if index % 3 == 0
        else "1200-1399"
    )
    return {
        "schema": SEMANTIC_POLICY_SCHEMA,
        "replay_id": f"fixture-{split}-{index}",
        "game_group": f"fixture-{split}-{index}",
        "split": split,
        "turn": (index % 5) + 1,
        "turn_band": "2-4" if index % 5 else "1",
        "side": "p1",
        "rating": 1650,
        "rating_band": rating_band,
        "public_state": _state((index % 5) + 1),
        "semantic_label": {
            "actions": [
                {
                    "slot": 1,
                    "kind": "move",
                    "move": move_a,
                    "gimmicks": [],
                },
                {
                    "slot": 2,
                    "kind": "move",
                    "move": move_b,
                    "gimmicks": [],
                },
            ],
            "action_family": "move+move",
        },
        "exact_menu_context": {},
        "source": {
            "trajectory_sha256": "a" * 64,
            "raw_sha256": "b" * 64,
            "trajectory_schema": "showdown-public-trajectory-v1",
        },
    }


def _write_shard(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def _install_dataset(data_root: Path) -> str:
    run_id = "fixturesemanticrun0001"
    layout = initialize_layout(data_root)
    run_dir = (
        layout.processed
        / "replay-policy"
        / DEFAULT_FORMAT
        / "runs"
        / run_id
    )
    train_rows = [_row(index, split="train") for index in range(20)]
    validation_rows = [_row(index, split="validation") for index in range(4)]
    test_rows = [_row(index + 4, split="test") for index in range(4)]
    test_rows[-1]["semantic_label"] = {
        "actions": [
            {
                "slot": 1,
                "kind": "move",
                "move": "unseenalpha",
                "gimmicks": [],
            },
            {
                "slot": 2,
                "kind": "move",
                "move": "unseenbeta",
                "gimmicks": [],
            },
        ],
        "action_family": "move+move",
    }
    _write_shard(run_dir / "train" / "part-00000.jsonl.gz", train_rows)
    _write_shard(
        run_dir / "validation" / "part-00000.jsonl.gz",
        validation_rows,
    )
    _write_shard(run_dir / "test" / "part-00000.jsonl.gz", test_rows)

    summary = {
        "schema": SEMANTIC_AUDIT_SCHEMA,
        "policy_schema": SEMANTIC_POLICY_SCHEMA,
        "run_id": run_id,
        "format_id": DEFAULT_FORMAT,
        "source_fingerprint": "c" * 64,
        "showdown_revision": "d" * 40,
        "semantic_trainable_rows": 28,
        "split_rows": {
            "train": 20,
            "validation": 4,
            "test": 4,
        },
        "dataset": {
            "root": (
                f"processed/replay-policy/{DEFAULT_FORMAT}/runs/{run_id}"
            ),
            "files": [
                {"path": "train/part-00000.jsonl.gz", "rows": 20},
                {"path": "validation/part-00000.jsonl.gz", "rows": 4},
                {"path": "test/part-00000.jsonl.gz", "rows": 4},
            ],
        },
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    latest = layout.processed / "replay-policy" / DEFAULT_FORMAT / "latest-summary.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_id


def _install_dataset_for_format(
    data_root: Path,
    *,
    format_id: str,
    run_id: str,
    move_prefix: str,
) -> str:
    layout = initialize_layout(data_root)
    run_dir = (
        layout.processed
        / "replay-policy"
        / format_id
        / "runs"
        / run_id
    )

    def rows_for(split: str, count: int, *, offset: int = 0) -> list[dict]:
        rows = []
        for index in range(count):
            row = _row(index + offset, split=split)
            for action in row["semantic_label"]["actions"]:
                action["move"] = f"{move_prefix}-{action['move']}"
            rows.append(row)
        return rows

    train_rows = rows_for("train", 20)
    validation_rows = rows_for("validation", 4)
    test_rows = rows_for("test", 4, offset=4)
    _write_shard(run_dir / "train" / "part-00000.jsonl.gz", train_rows)
    _write_shard(
        run_dir / "validation" / "part-00000.jsonl.gz",
        validation_rows,
    )
    _write_shard(run_dir / "test" / "part-00000.jsonl.gz", test_rows)

    summary = {
        "schema": SEMANTIC_AUDIT_SCHEMA,
        "policy_schema": SEMANTIC_POLICY_SCHEMA,
        "run_id": run_id,
        "format_id": format_id,
        "source_fingerprint": (move_prefix[0] * 64),
        "showdown_revision": "d" * 40,
        "semantic_trainable_rows": 28,
        "split_rows": {
            "train": 20,
            "validation": 4,
            "test": 4,
        },
        "dataset": {
            "root": f"processed/replay-policy/{format_id}/runs/{run_id}",
            "files": [
                {"path": "train/part-00000.jsonl.gz", "rows": 20},
                {"path": "validation/part-00000.jsonl.gz", "rows": 4},
                {"path": "test/part-00000.jsonl.gz", "rows": 4},
            ],
        },
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    latest = layout.processed / "replay-policy" / format_id / "latest-summary.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_id


def test_tiny_semantic_policy_training_produces_reproducible_artifacts(
    tmp_path: Path,
):
    data_root = tmp_path / "external"
    run_id = _install_dataset(data_root)
    config = TrainingConfig(
        data_root=data_root,
        run_id=run_id,
        epochs=1,
        batch_size=4,
        train_negatives=3,
        eval_negatives=15,
        embedding_dim=8,
        state_buckets=256,
        action_buckets=256,
        learning_rate=0.05,
        shuffle_buffer=8,
        seed=7,
    )

    first = train_semantic_policy(config)
    second = train_semantic_policy(config)

    assert first["schema"] == TRAINING_REPORT_SCHEMA
    assert first["model_schema"] == MODEL_SCHEMA
    assert first["dataset"]["run_id"] == run_id
    assert first["action_vocabulary"]["entries"] == 20
    assert first["epochs"][0]["training_rows"] == 20
    assert first["validation"]["candidate_count"] == 16
    assert first["validation"]["overall"]["rows"] == 4
    assert first["test"]["overall"]["rows"] == 4
    assert first["test"]["training_vocabulary_status"]["seen"]["rows"] == 3
    assert first["test"]["training_vocabulary_status"]["unseen"]["rows"] == 1
    assert first["test"]["state_blind_baseline"]["uses_public_state"] is False
    assert first["authority"]["live_decision_authority"] is False
    assert first["artifacts"]["model"]["bytes"] > 0
    assert first["artifacts"]["vocabulary"]["bytes"] > 0
    assert second["training_id"] == first["training_id"]
    assert second["generated_at"] == first["generated_at"]

    status = training_status(data_root, run_id=run_id)
    assert status["available"] is True
    assert status["training_id"] == first["training_id"]


def test_training_report_keeps_sampled_metrics_distinct_from_legal_menu_metrics(
    tmp_path: Path,
):
    data_root = tmp_path / "external"
    run_id = _install_dataset(data_root)
    report = train_semantic_policy(
        TrainingConfig(
            data_root=data_root,
            run_id=run_id,
            epochs=1,
            batch_size=5,
            train_negatives=3,
            eval_negatives=15,
            embedding_dim=8,
            state_buckets=256,
            action_buckets=256,
            shuffle_buffer=8,
            seed=8,
        )
    )

    assert "not exact legal-menu recall" in report["validation"]["warning"]
    assert report["validation"]["candidate_source"].startswith(
        "same-action-family semantic labels"
    )
    assert set(report["validation"]["overall"]) >= {
        "sampled_recall_at_1",
        "sampled_recall_at_4",
        "sampled_recall_at_8",
        "sampled_recall_at_16",
    }


def test_saved_model_can_be_re_evaluated_and_addressed_by_alias(tmp_path: Path):
    data_root = tmp_path / "external"
    run_id = _install_dataset(data_root)
    report = train_semantic_policy(
        TrainingConfig(
            data_root=data_root,
            run_id=run_id,
            epochs=1,
            batch_size=4,
            train_negatives=3,
            eval_negatives=15,
            embedding_dim=8,
            state_buckets=256,
            action_buckets=256,
            shuffle_buffer=8,
            seed=11,
        )
    )

    register_dataset_alias(
        data_root,
        alias="fixture-semantic-v1",
        run_id=run_id,
    )
    register_training_alias(
        data_root,
        alias="fixture-bc-v1",
        training_id=report["training_id"],
        dataset_reference="fixture-semantic-v1",
    )

    diagnostics = evaluate_saved_training(data_root, "fixture-bc-v1")

    assert diagnostics["training_id"] == report["training_id"]
    assert diagnostics["dataset_run_id"] == run_id
    assert diagnostics["test"]["training_vocabulary_status"]["seen"]["rows"] == 3
    assert diagnostics["test"]["training_vocabulary_status"]["unseen"]["rows"] == 1
    assert diagnostics["test"]["state_blind_baseline"]["uses_public_state"] is False
    assert diagnostics["authority"]["live_decision_authority"] is False
    assert (
        data_root
        / "models"
        / "semantic-policy"
        / run_id
        / report["training_id"]
        / "diagnostics.json"
    ).is_file()

    comparison = compare_training_runs(
        data_root,
        ["fixture-bc-v1", report["training_id"]],
    )
    table = format_comparison_table(comparison)
    assert len(comparison) == 2
    assert comparison[0]["blind_top1"] is not None
    assert comparison[0]["unseen_rows"] == 1
    assert "blind1" in table
    assert "unseen1" in table


def test_training_can_register_aliases_without_changing_training_identity(tmp_path: Path):
    data_root = tmp_path / "external"
    run_id = _install_dataset(data_root)
    base = TrainingConfig(
        data_root=data_root,
        run_id=run_id,
        epochs=1,
        batch_size=4,
        train_negatives=3,
        eval_negatives=15,
        embedding_dim=8,
        state_buckets=256,
        action_buckets=256,
        shuffle_buffer=8,
        seed=12,
    )
    first = train_semantic_policy(base)
    aliased = train_semantic_policy(
        TrainingConfig(
            **{
                **base.__dict__,
                "dataset_alias": "fixture-dataset-alias",
                "training_alias": "fixture-training-alias",
            }
        )
    )

    assert aliased["training_id"] == first["training_id"]


def test_mixed_training_uses_extra_train_rows_but_primary_eval_splits(
    tmp_path: Path,
):
    data_root = tmp_path / "external"
    primary_run = _install_dataset(data_root)
    extra_format = "gen9championsvgc2026regmb"
    extra_run = _install_dataset_for_format(
        data_root,
        format_id=extra_format,
        run_id="fixturesemanticrunmb0001",
        move_prefix="mb",
    )

    report = train_semantic_policy(
        TrainingConfig(
            data_root=data_root,
            run_id=primary_run,
            epochs=1,
            batch_size=4,
            train_negatives=3,
            eval_negatives=15,
            embedding_dim=8,
            state_buckets=256,
            action_buckets=256,
            shuffle_buffer=8,
            seed=21,
            extra_datasets=(f"{extra_format}:{extra_run}",),
        )
    )

    assert report["epochs"][0]["training_rows"] == 40
    assert report["validation"]["overall"]["rows"] == 4
    assert report["test"]["overall"]["rows"] == 4
    assert [
        (entry["format_id"], entry["run_id"])
        for entry in report["training_datasets"]
    ] == [
        (DEFAULT_FORMAT, primary_run),
        (extra_format, extra_run),
    ]
    assert report["dataset"]["run_id"] == primary_run


def test_duplicate_training_dataset_is_rejected(tmp_path: Path):
    data_root = tmp_path / "external"
    primary_run = _install_dataset(data_root)

    with pytest.raises(
        SemanticPolicyTrainingError,
        match="was supplied twice",
    ):
        train_semantic_policy(
            TrainingConfig(
                data_root=data_root,
                run_id=primary_run,
                epochs=1,
                batch_size=4,
                train_negatives=3,
                eval_negatives=15,
                embedding_dim=8,
                state_buckets=256,
                action_buckets=256,
                shuffle_buffer=8,
                seed=22,
                extra_datasets=(f"{DEFAULT_FORMAT}:{primary_run}",),
            )
        )


def test_training_can_warm_start_from_compatible_saved_model(tmp_path: Path):
    data_root = tmp_path / "external"
    primary_run = _install_dataset(data_root)
    pretrain_format = "gen9championsvgc2026regmb"
    pretrain_run = _install_dataset_for_format(
        data_root,
        format_id=pretrain_format,
        run_id="fixturesemanticrunmb0002",
        move_prefix="pretrain",
    )
    common = {
        "epochs": 1,
        "batch_size": 4,
        "train_negatives": 3,
        "eval_negatives": 15,
        "embedding_dim": 8,
        "state_buckets": 256,
        "action_buckets": 256,
        "shuffle_buffer": 8,
    }
    pretrain = train_semantic_policy(
        TrainingConfig(
            data_root=data_root,
            format_id=pretrain_format,
            run_id=pretrain_run,
            seed=23,
            **common,
        )
    )
    cold = train_semantic_policy(
        TrainingConfig(
            data_root=data_root,
            run_id=primary_run,
            seed=24,
            **common,
        )
    )
    fine_tuned = train_semantic_policy(
        TrainingConfig(
            data_root=data_root,
            run_id=primary_run,
            seed=24,
            initialize_from=pretrain["training_id"],
            **common,
        )
    )

    assert fine_tuned["training_id"] != cold["training_id"]
    assert fine_tuned["initialization"]["training_id"] == pretrain["training_id"]
    assert fine_tuned["initialization"]["dataset_run_id"] == pretrain_run
    assert fine_tuned["initialization"]["optimizer_state"] == "reset"
    assert fine_tuned["epochs"][0]["training_rows"] == 20


def test_warm_start_rejects_incompatible_embedding_shape(tmp_path: Path):
    data_root = tmp_path / "external"
    primary_run = _install_dataset(data_root)
    pretrain = train_semantic_policy(
        TrainingConfig(
            data_root=data_root,
            run_id=primary_run,
            epochs=1,
            batch_size=4,
            train_negatives=3,
            eval_negatives=15,
            embedding_dim=8,
            state_buckets=256,
            action_buckets=256,
            shuffle_buffer=8,
            seed=25,
        )
    )

    with pytest.raises(
        SemanticPolicyTrainingError,
        match="initialization embedding_dim",
    ):
        train_semantic_policy(
            TrainingConfig(
                data_root=data_root,
                run_id=primary_run,
                epochs=1,
                batch_size=4,
                train_negatives=3,
                eval_negatives=15,
                embedding_dim=16,
                state_buckets=256,
                action_buckets=256,
                shuffle_buffer=8,
                seed=26,
                initialize_from=pretrain["training_id"],
            )
        )
