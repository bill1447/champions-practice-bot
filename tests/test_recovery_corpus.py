from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from champions_practice.recovery_corpus import (
    POOL_SCHEMA,
    CorpusRunConfig,
    ExactTeamRecord,
    RecoveryCorpusError,
    TeamPools,
    _conditioning_batches,
    _run_id,
    fixed_team_pools,
    load_exact_team_records,
    load_team_pool_manifest,
    select_team_pools,
    translate_preview,
    validate_team_for_battle,
    write_team_pool_manifest,
)


def _record(
    team_id: str,
    *,
    regulation: str = "mc",
    species: tuple[str, ...] = (
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
    ),
    digest: str | None = None,
) -> ExactTeamRecord:
    return ExactTeamRecord(
        regulation=regulation,
        team_id=team_id,
        format_id=f"format-{regulation}",
        validator_format_id=f"format-{regulation}",
        regulation_validation_authoritative=True,
        canonical_sha256=digest or hashlib.sha256(team_id.encode()).hexdigest(),
        canonical_text=f"team {team_id}\n",
        packed_team=f"packed-{team_id}",
        species=species,
        validator_revision="revision",
    )


def test_team_pool_selection_is_deterministic_and_disjoint():
    records = tuple(_record(f"team-{index}") for index in range(8))

    first = select_team_pools(
        records,
        pool_seed=145,
        evaluation_per_regulation=3,
    )
    second = select_team_pools(
        reversed(records),
        pool_seed=145,
        evaluation_per_regulation=3,
    )

    assert [record.key for record in first.evaluation] == [
        record.key for record in second.evaluation
    ]
    assert {record.key for record in first.training}.isdisjoint(
        {record.key for record in first.evaluation}
    )
    assert len(first.training) + len(first.evaluation) == len(records)


def test_team_pool_selection_prefers_species_diversity():
    records = (
        _record("baseline-1"),
        _record("baseline-2"),
        _record(
            "novel",
            species=("A", "B", "C", "D", "E", "Z"),
        ),
    )

    pools = select_team_pools(
        records,
        pool_seed=145,
        evaluation_per_regulation=2,
    )

    assert "mc:novel" in {record.key for record in pools.evaluation}


def test_pool_manifest_round_trip_and_hash_drift_detection(tmp_path: Path):
    records = tuple(_record(f"team-{index}") for index in range(4))
    pools = select_team_pools(
        records,
        pool_seed=145,
        evaluation_per_regulation=2,
    )
    path = tmp_path / "pools.json"

    write_team_pool_manifest(pools, path)
    loaded = load_team_pool_manifest(path, records)

    assert loaded == pools

    changed = list(records)
    changed[0] = _record(
        changed[0].team_id,
        digest="f" * 64,
    )
    with pytest.raises(RecoveryCorpusError, match="canonical hash changed"):
        load_team_pool_manifest(path, changed)


def test_pool_manifest_rejects_canonical_truth_overlap(tmp_path: Path):
    digest = "b" * 64
    training = _record("training-alias", digest=digest)
    evaluation = _record("evaluation-alias", digest=digest)
    pools = TeamPools(
        training=(training,),
        evaluation=(evaluation,),
        pool_seed=145,
        evaluation_per_regulation=1,
    )
    path = tmp_path / "pools.json"
    write_team_pool_manifest(pools, path)

    with pytest.raises(RecoveryCorpusError, match="canonical hidden truth"):
        load_team_pool_manifest(path, (training, evaluation))


def test_fixed_pool_manifest_refuses_seed_change_without_refresh(tmp_path: Path):
    records = tuple(_record(f"team-{index}") for index in range(4))
    path = tmp_path / "pools.json"

    fixed_team_pools(
        records,
        path=path,
        pool_seed=145,
        evaluation_per_regulation=2,
        refresh=True,
    )

    with pytest.raises(RecoveryCorpusError, match="different pool seed"):
        fixed_team_pools(
            records,
            path=path,
            pool_seed=146,
            evaluation_per_regulation=2,
            refresh=False,
        )




def test_team_pool_split_blocks_cross_regulation_canonical_alias():
    digest = "c" * 64
    records = (
        _record("mc-only", regulation="mc", digest=digest),
        _record("mb-alias", regulation="mb", digest=digest),
        _record("other", regulation="mb"),
    )

    pools = select_team_pools(
        records,
        pool_seed=145,
        evaluation_per_regulation=1,
    )

    assert "mc:mc-only" in {record.key for record in pools.evaluation}
    assert "mb:mb-alias" not in {record.key for record in pools.training}
    assert {
        record.canonical_sha256
        for record in pools.training
    }.isdisjoint(
        {
            record.canonical_sha256
            for record in pools.evaluation
        }
    )


def test_team_pool_split_never_leaks_canonical_duplicate_truth():
    duplicate_hash = "a" * 64
    records = (
        _record("alias-1", digest=duplicate_hash),
        _record("alias-2", digest=duplicate_hash),
        _record("other-1"),
        _record("other-2"),
    )

    pools = select_team_pools(
        records,
        pool_seed=145,
        evaluation_per_regulation=1,
    )

    training_hashes = {
        record.canonical_sha256
        for record in pools.training
    }
    evaluation_hashes = {
        record.canonical_sha256
        for record in pools.evaluation
    }
    assert training_hashes.isdisjoint(evaluation_hashes)


def test_run_id_binds_frozen_training_pool():
    evaluation = (_record("eval"),)
    first = TeamPools(
        training=(_record("train-a"),),
        evaluation=evaluation,
        pool_seed=145,
        evaluation_per_regulation=1,
    )
    second = TeamPools(
        training=(_record("train-b"),),
        evaluation=evaluation,
        pool_seed=145,
        evaluation_per_regulation=1,
    )
    config = CorpusRunConfig(battles=1, turns=1)

    assert _run_id(
        config,
        first,
        showdown_revision="a" * 40,
    ) != _run_id(
        config,
        second,
        showdown_revision="a" * 40,
    )


def test_conditioning_batches_preserve_production_adaptive_shape():
    config = CorpusRunConfig(conditioning_batch_sizes=(2, 4))

    batches = _conditioning_batches(
        config,
        battle_index=3,
        turn_number=2,
    )

    assert [len(batch) for batch in batches] == [2, 4]
    assert len(set(batches[0] + batches[1])) == 6


def test_config_rejects_invalid_conditioning_batch_shape():
    with pytest.raises(ValueError, match="conditioning_batch_sizes"):
        CorpusRunConfig(conditioning_batch_sizes=(2, 0))


def test_translate_preview_preserves_selected_species_across_set_order():
    translated = translate_preview(
        "team 1256",
        source_species=("A", "B", "C", "D", "E", "F"),
        target_species=("F", "C", "A", "E", "B", "D"),
    )

    assert translated == "team 3541"


def test_translate_preview_accepts_showdown_comma_separated_choice():
    translated = translate_preview(
        "team 2, 1, 3, 6",
        source_species=("A", "B", "C", "D", "E", "F"),
        target_species=("F", "C", "A", "E", "B", "D"),
    )

    assert translated == "team 5321"


def test_translate_preview_rejects_nonmatching_team():
    with pytest.raises(RecoveryCorpusError, match="not present"):
        translate_preview(
            "team 1256",
            source_species=("A", "B", "C", "D", "E", "F"),
            target_species=("A", "B", "C", "D", "E", "Z"),
        )


class _Validator:
    def __init__(self, *, valid: bool = True):
        self.valid = valid
        self.calls = 0

    def validate_team(self, *, battle_format: str, team_text: str):
        self.calls += 1
        return {
            "valid": self.valid,
            "problems": [] if self.valid else ["illegal"],
            "team_size": 6,
            "canonical_text": f"{battle_format}\n{team_text}",
        }


def test_battle_validation_is_format_specific_and_cached():
    validator = _Validator()
    cache: dict[tuple[str, str], str] = {}
    record = _record("one")

    first = validate_team_for_battle(
        validator,
        record,
        battle_format="format-a",
        cache=cache,
    )
    second = validate_team_for_battle(
        validator,
        record,
        battle_format="format-a",
        cache=cache,
    )
    third = validate_team_for_battle(
        validator,
        record,
        battle_format="format-b",
        cache=cache,
    )

    assert first == second
    assert third != first
    assert validator.calls == 2


def test_battle_validation_fails_closed_on_invalid_team():
    with pytest.raises(RecoveryCorpusError, match="not valid"):
        validate_team_for_battle(
            _Validator(valid=False),
            _record("one"),
            battle_format="format-a",
        )


def _create_manifest(root: Path, canonical: bytes) -> Path:
    database = root / "teams" / "manifests" / "teams.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    relative = Path("teams/canonical/mc/team-1/team.txt")
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical)
    digest = hashlib.sha256(canonical).hexdigest()
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE teams (
                regulation TEXT,
                team_id TEXT,
                format_id TEXT,
                validator_format_id TEXT,
                regulation_validation_authoritative INTEGER,
                canonical_relative_path TEXT,
                canonical_sha256 TEXT,
                packed_team TEXT,
                sets_json TEXT,
                species_json TEXT,
                validator_revision TEXT,
                exact_team_ready INTEGER,
                validation_state TEXT
            )
            """
        )
        sets = [
            {"species": species}
            for species in ("A", "B", "C", "D", "E", "F")
        ]
        connection.execute(
            """
            INSERT INTO teams VALUES (
                'mc', 'team-1', 'format-mc', 'format-mc', 1,
                ?, ?, 'packed', ?, ?, 'revision', 1, 'valid'
            )
            """,
            (
                relative.as_posix(),
                digest,
                json.dumps(sets),
                json.dumps(["A", "B", "C", "D", "E", "F"]),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def test_exact_team_loader_verifies_external_canonical_bytes(tmp_path: Path):
    root = tmp_path / "external"
    canonical_path = _create_manifest(root, b"canonical team\n")

    records = load_exact_team_records(root, regulations=("mc",))

    assert len(records) == 1
    assert records[0].canonical_text == "canonical team\n"
    assert records[0].species == ("A", "B", "C", "D", "E", "F")

    canonical_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RecoveryCorpusError, match="hash mismatch"):
        load_exact_team_records(root, regulations=("mc",))


def test_pool_manifest_schema_is_explicit(tmp_path: Path):
    records = (_record("one"), _record("two"))
    pools = select_team_pools(
        records,
        pool_seed=145,
        evaluation_per_regulation=1,
    )
    path = tmp_path / "pools.json"

    write_team_pool_manifest(pools, path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema"] == POOL_SCHEMA


def test_config_rejects_zero_battles():
    with pytest.raises(ValueError, match="battles"):
        CorpusRunConfig(battles=0)
