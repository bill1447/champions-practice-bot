"""Deterministic exact-team corpus runner for offline recovery soundness.

Bulk team truth and generated reports live outside Git. This module reads the
validated team manifest, freezes deterministic train/evaluation pools, validates
selected teams against the concrete battle format, and measures true-world
survival without granting recovery any live authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from champions_practice.observation_beliefs import (
    BeliefParticle,
    identity_member_lineage,
    public_observation_mismatch_paths,
    public_observation_signature,
)
from champions_practice.recovery_soundness import (
    ConditioningSoundnessReport,
    RecoverySoundnessReport,
    TrueWorldConditioningCase,
    TrueWorldConditioningOutcome,
    TrueWorldTransitionOutcome,
    evaluate_true_world_conditioning,
    evaluate_true_world_transition,
    generate_true_world_transition,
    write_conditioning_false_exclusion_regressions,
    write_false_exclusion_regressions,
)
from champions_practice.replay_corpus import DATA_ROOT_ENV, ensure_external_data_root
from champions_practice.search_worker import (
    HypotheticalSearchWorker,
    TeamValidationWorker,
)
from champions_practice.team_corpus import REGULATION_BY_KEY


POOL_SCHEMA = "recovery-team-pools-v1"
RUN_SCHEMA = "recovery-soundness-corpus-v1"
DEFAULT_EVALUATION_PER_REGULATION = 48
DEFAULT_BATTLES = 64
DEFAULT_TURNS = 8
DEFAULT_MAX_DECOYS = 7
DEFAULT_CONDITIONING_BATCH_SIZES = (2, 4)
DEFAULT_POOL_SEED = 145
DEFAULT_BATTLE_SEED = 14501
DEFAULT_ACTION_SEED = 14502
DEFAULT_CONDITIONING_SEED = 14503
DEFAULT_RESAMPLE_SEED = 14504


class RecoveryCorpusError(RuntimeError):
    """Corpus measurement could not continue safely."""


class TeamValidator(Protocol):
    showdown_revision: str

    def validate_team(
        self,
        *,
        battle_format: str,
        team_text: str,
    ) -> dict[str, Any]: ...


class CorpusWorker(Protocol):
    def create_state(
        self,
        *,
        battle_format: str,
        p1_team: str,
        p2_team: str,
        p1_preview: str | None = None,
        p2_preview: str | None = None,
        p1_name: str = "Search P1",
        p2_name: str = "Search P2",
        seed: str | None = None,
    ) -> dict[str, Any]: ...

    def branch_many(
        self,
        *,
        state: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...

    def state_view(
        self,
        *,
        state: dict[str, Any],
        side: str,
        previews: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]: ...

    def legal_choices(
        self,
        *,
        state: dict[str, Any],
        side: str,
    ) -> list[str]: ...


@dataclass(frozen=True)
class ExactTeamRecord:
    regulation: str
    team_id: str
    format_id: str
    validator_format_id: str
    regulation_validation_authoritative: bool
    canonical_sha256: str
    canonical_text: str
    packed_team: str
    species: tuple[str, ...]
    validator_revision: str

    @property
    def key(self) -> str:
        return f"{self.regulation}:{self.team_id}"

    @property
    def species_signature(self) -> tuple[str, ...]:
        return tuple(sorted(_to_id(species) for species in self.species))


@dataclass(frozen=True)
class TeamPools:
    training: tuple[ExactTeamRecord, ...]
    evaluation: tuple[ExactTeamRecord, ...]
    pool_seed: int
    evaluation_per_regulation: int

    @property
    def all(self) -> tuple[ExactTeamRecord, ...]:
        return self.training + self.evaluation


@dataclass(frozen=True)
class CorpusRunConfig:
    regulations: tuple[str, ...] = ("mc",)
    battles: int = DEFAULT_BATTLES
    turns: int = DEFAULT_TURNS
    max_decoys: int = DEFAULT_MAX_DECOYS
    conditioning_batch_sizes: tuple[int, ...] = DEFAULT_CONDITIONING_BATCH_SIZES
    pool_seed: int = DEFAULT_POOL_SEED
    evaluation_per_regulation: int = DEFAULT_EVALUATION_PER_REGULATION
    battle_seed: int = DEFAULT_BATTLE_SEED
    action_seed: int = DEFAULT_ACTION_SEED
    conditioning_seed: int = DEFAULT_CONDITIONING_SEED
    resample_seed: int = DEFAULT_RESAMPLE_SEED
    allow_nonauthoritative_regulation: bool = False

    def __post_init__(self) -> None:
        if not self.regulations:
            raise ValueError("at least one regulation is required")
        unknown = [key for key in self.regulations if key not in REGULATION_BY_KEY]
        if unknown:
            raise ValueError(f"unknown regulations: {unknown!r}")
        for label, value in (
            ("battles", self.battles),
            ("turns", self.turns),
            ("evaluation_per_regulation", self.evaluation_per_regulation),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if (
            not self.conditioning_batch_sizes
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in self.conditioning_batch_sizes
            )
        ):
            raise ValueError(
                "conditioning_batch_sizes must contain positive integers"
            )
        if (
            isinstance(self.max_decoys, bool)
            or not isinstance(self.max_decoys, int)
            or self.max_decoys < 0
        ):
            raise ValueError("max_decoys must be a non-negative integer")


@dataclass(frozen=True)
class CorpusRunResult:
    run_id: str
    run_dir: Path
    summary_path: Path
    cases_path: Path
    pool_path: Path
    reachability: RecoverySoundnessReport
    conditioning: ConditioningSoundnessReport
    summary: dict[str, Any]


@dataclass(frozen=True)
class _BattleWorld:
    record: ExactTeamRecord
    state: dict[str, Any]
    world_id: str
    history_id: str
    p1_lineage: tuple[int, ...]
    p2_lineage: tuple[int, ...]

    def particle(self) -> BeliefParticle:
        return BeliefParticle(
            state=self.state,
            weight=1.0,
            world_id=self.world_id,
            history_id=self.history_id,
            p1_member_lineage=self.p1_lineage,
            p2_member_lineage=self.p2_lineage,
        )


def _to_id(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _hash_hex(*parts: object) -> str:
    joined = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _hash_index(length: int, *parts: object) -> int:
    if length <= 0:
        raise ValueError("cannot choose from an empty sequence")
    return int(_hash_hex(*parts)[:16], 16) % length


def _sodium_seed(*parts: object) -> str:
    return "sodium," + _hash_hex(*parts)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _manifest_path(data_root: Path) -> Path:
    return data_root / "teams" / "manifests" / "teams.sqlite3"


def load_exact_team_records(
    data_root: str | Path,
    *,
    regulations: Iterable[str] = ("mc", "mb", "ma"),
) -> tuple[ExactTeamRecord, ...]:
    root = ensure_external_data_root(data_root)
    selected = tuple(dict.fromkeys(regulations))
    if not selected:
        return ()
    unknown = [key for key in selected if key not in REGULATION_BY_KEY]
    if unknown:
        raise ValueError(f"unknown regulations: {unknown!r}")
    database = _manifest_path(root)
    if not database.is_file():
        raise RecoveryCorpusError(f"team manifest is missing: {database}")

    placeholders = ",".join("?" for _ in selected)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"""
            SELECT regulation, team_id, format_id, validator_format_id,
                   regulation_validation_authoritative, canonical_relative_path,
                   canonical_sha256, packed_team, sets_json, species_json,
                   validator_revision
            FROM teams
            WHERE exact_team_ready = 1
              AND validation_state = 'valid'
              AND regulation IN ({placeholders})
            ORDER BY regulation, team_id
            """,
            selected,
        ).fetchall()
    finally:
        connection.close()

    records: list[ExactTeamRecord] = []
    for row in rows:
        relative = row["canonical_relative_path"]
        expected_sha = row["canonical_sha256"]
        packed = row["packed_team"]
        if not isinstance(relative, str) or not relative:
            raise RecoveryCorpusError(
                f"exact-ready team {row['regulation']}:{row['team_id']} "
                "has no canonical path"
            )
        path = (root / Path(relative)).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise RecoveryCorpusError(
                f"canonical team path escapes external root for "
                f"{row['regulation']}:{row['team_id']}"
            ) from error
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise RecoveryCorpusError(f"cannot read canonical team: {path}") from error
        actual_sha = hashlib.sha256(payload).hexdigest()
        if not isinstance(expected_sha, str) or actual_sha != expected_sha:
            raise RecoveryCorpusError(
                f"canonical team hash mismatch for {row['regulation']}:{row['team_id']}"
            )
        if not isinstance(packed, str) or not packed:
            raise RecoveryCorpusError(
                f"exact-ready team {row['regulation']}:{row['team_id']} has no packed team"
            )
        try:
            sets = json.loads(row["sets_json"] or "null")
            source_species = json.loads(row["species_json"] or "[]")
        except json.JSONDecodeError as error:
            raise RecoveryCorpusError("team manifest contains invalid JSON") from error
        species: list[str] = []
        if isinstance(sets, list):
            for team_set in sets:
                if isinstance(team_set, dict) and isinstance(team_set.get("species"), str):
                    species.append(team_set["species"])
        if len(species) != 6 and isinstance(source_species, list):
            species = [value for value in source_species if isinstance(value, str)]
        if len(species) != 6:
            raise RecoveryCorpusError(
                f"exact-ready team {row['regulation']}:{row['team_id']} "
                "does not expose six ordered species"
            )
        records.append(
            ExactTeamRecord(
                regulation=row["regulation"],
                team_id=row["team_id"],
                format_id=row["format_id"],
                validator_format_id=row["validator_format_id"],
                regulation_validation_authoritative=bool(
                    row["regulation_validation_authoritative"]
                ),
                canonical_sha256=expected_sha,
                canonical_text=payload.decode("utf-8"),
                packed_team=packed,
                species=tuple(species),
                validator_revision=row["validator_revision"] or "",
            )
        )
    return tuple(records)


def _species_pairs(record: ExactTeamRecord) -> frozenset[tuple[str, str]]:
    ids = sorted(record.species_signature)
    return frozenset(
        (ids[left], ids[right])
        for left in range(len(ids))
        for right in range(left + 1, len(ids))
    )


def _diverse_evaluation_subset(
    records: list[ExactTeamRecord],
    *,
    count: int,
    pool_seed: int,
    regulation: str,
) -> list[ExactTeamRecord]:
    remaining = sorted(
        records,
        key=lambda record: _hash_hex(
            pool_seed,
            regulation,
            record.team_id,
            record.canonical_sha256,
        ),
    )
    selected: list[ExactTeamRecord] = []
    covered_species: set[str] = set()
    covered_pairs: set[tuple[str, str]] = set()
    while remaining and len(selected) < min(count, len(records)):
        best = min(
            remaining,
            key=lambda record: (
                -len(set(record.species_signature) - covered_species),
                -len(set(_species_pairs(record)) - covered_pairs),
                _hash_hex(
                    pool_seed,
                    regulation,
                    record.team_id,
                    record.canonical_sha256,
                ),
            ),
        )
        selected.append(best)
        covered_species.update(best.species_signature)
        covered_pairs.update(_species_pairs(best))
        remaining.remove(best)
    return selected


def select_team_pools(
    records: Iterable[ExactTeamRecord],
    *,
    pool_seed: int = DEFAULT_POOL_SEED,
    evaluation_per_regulation: int = DEFAULT_EVALUATION_PER_REGULATION,
) -> TeamPools:
    if evaluation_per_regulation <= 0:
        raise ValueError("evaluation_per_regulation must be positive")
    grouped: dict[str, list[ExactTeamRecord]] = defaultdict(list)
    for record in records:
        grouped[record.regulation].append(record)

    evaluation: list[ExactTeamRecord] = []
    for regulation in sorted(grouped):
        group = grouped[regulation]
        by_canonical: dict[str, list[ExactTeamRecord]] = defaultdict(list)
        for record in group:
            by_canonical[record.canonical_sha256].append(record)

        representatives = [
            min(aliases, key=lambda record: record.key)
            for aliases in by_canonical.values()
        ]
        evaluation.extend(
            _diverse_evaluation_subset(
                representatives,
                count=evaluation_per_regulation,
                pool_seed=pool_seed,
                regulation=regulation,
            )
        )

    # Canonical bytes identify hidden truth for split purposes. If an evaluation
    # truth appears under another event or regulation provenance row, none of
    # those aliases may enter training.
    evaluation_hashes = {
        record.canonical_sha256
        for record in evaluation
    }
    training = [
        record
        for group in grouped.values()
        for record in group
        if record.canonical_sha256 not in evaluation_hashes
    ]

    return TeamPools(
        training=tuple(sorted(training, key=lambda record: record.key)),
        evaluation=tuple(sorted(evaluation, key=lambda record: record.key)),
        pool_seed=pool_seed,
        evaluation_per_regulation=evaluation_per_regulation,
    )

def _pool_member(record: ExactTeamRecord) -> dict[str, Any]:
    return {
        "regulation": record.regulation,
        "team_id": record.team_id,
        "canonical_sha256": record.canonical_sha256,
        "validator_revision": record.validator_revision,
        "species": list(record.species),
    }


def write_team_pool_manifest(pools: TeamPools, path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    payload = {
        "schema": POOL_SCHEMA,
        "pool_seed": pools.pool_seed,
        "evaluation_per_regulation": pools.evaluation_per_regulation,
        "training": [_pool_member(record) for record in pools.training],
        "evaluation": [_pool_member(record) for record in pools.evaluation],
    }
    _atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return target


def load_team_pool_manifest(
    path: str | Path,
    records: Iterable[ExactTeamRecord],
) -> TeamPools:
    target = Path(path).expanduser().resolve()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryCorpusError(f"cannot read team pool manifest: {target}") from error
    if payload.get("schema") != POOL_SCHEMA:
        raise RecoveryCorpusError("unsupported team pool manifest schema")
    by_key = {record.key: record for record in records}

    def resolve(entries: object, label: str) -> tuple[ExactTeamRecord, ...]:
        if not isinstance(entries, list):
            raise RecoveryCorpusError(f"pool manifest {label} must be a list")
        output: list[ExactTeamRecord] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise RecoveryCorpusError(f"pool manifest {label} entry is invalid")
            regulation = entry.get("regulation")
            team_id = entry.get("team_id")
            digest = entry.get("canonical_sha256")
            key = f"{regulation}:{team_id}"
            record = by_key.get(key)
            if record is None:
                raise RecoveryCorpusError(f"pool member is no longer exact-ready: {key}")
            if record.canonical_sha256 != digest:
                raise RecoveryCorpusError(f"pool member canonical hash changed: {key}")
            if key in seen:
                raise RecoveryCorpusError(f"duplicate pool member: {key}")
            seen.add(key)
            output.append(record)
        return tuple(output)

    training = resolve(payload.get("training"), "training")
    evaluation = resolve(payload.get("evaluation"), "evaluation")
    overlap = {record.key for record in training} & {record.key for record in evaluation}
    if overlap:
        raise RecoveryCorpusError(f"training/evaluation pools overlap: {sorted(overlap)!r}")
    truth_overlap = (
        {record.canonical_sha256 for record in training}
        & {record.canonical_sha256 for record in evaluation}
    )
    if truth_overlap:
        raise RecoveryCorpusError(
            "training/evaluation pools contain the same canonical hidden truth"
        )
    return TeamPools(
        training=training,
        evaluation=evaluation,
        pool_seed=int(payload.get("pool_seed")),
        evaluation_per_regulation=int(payload.get("evaluation_per_regulation")),
    )


def fixed_team_pools(
    records: Iterable[ExactTeamRecord],
    *,
    path: str | Path,
    pool_seed: int,
    evaluation_per_regulation: int,
    refresh: bool,
) -> TeamPools:
    target = Path(path).expanduser().resolve()
    materialized = tuple(records)
    if target.is_file() and not refresh:
        pools = load_team_pool_manifest(target, materialized)
        if pools.pool_seed != pool_seed:
            raise RecoveryCorpusError(
                "existing pool manifest uses a different pool seed; pass --refresh-pools"
            )
        if pools.evaluation_per_regulation != evaluation_per_regulation:
            raise RecoveryCorpusError(
                "existing pool manifest uses a different evaluation size; "
                "pass --refresh-pools"
            )
        return pools
    pools = select_team_pools(
        materialized,
        pool_seed=pool_seed,
        evaluation_per_regulation=evaluation_per_regulation,
    )
    write_team_pool_manifest(pools, target)
    return pools


def validate_team_for_battle(
    validator: TeamValidator,
    record: ExactTeamRecord,
    *,
    battle_format: str,
    cache: dict[tuple[str, str], str] | None = None,
) -> str:
    key = (battle_format, record.canonical_sha256)
    if cache is not None and key in cache:
        return cache[key]
    result = validator.validate_team(
        battle_format=battle_format,
        team_text=record.canonical_text,
    )
    if not result.get("valid") or result.get("team_size") != 6:
        problems = result.get("problems")
        raise RecoveryCorpusError(
            f"team {record.key} is not valid for {battle_format}: {problems!r}"
        )
    canonical = result.get("canonical_text")
    if not isinstance(canonical, str) or not canonical.strip():
        raise RecoveryCorpusError("battle-format validation returned no canonical team")
    if cache is not None:
        cache[key] = canonical
    return canonical


def choose_preview(
    worker: CorpusWorker,
    *,
    state: dict[str, Any],
    side: str,
    seed_parts: tuple[object, ...],
) -> str:
    choices = [
        choice
        for choice in worker.legal_choices(state=state, side=side)
        if choice.startswith("team ")
    ]
    if not choices:
        raise RecoveryCorpusError(f"no team-preview choices available for {side}")
    return choices[_hash_index(len(choices), *seed_parts, side, "preview")]


def _preview_indices(choice: str) -> tuple[int, ...]:
    match = re.fullmatch(r"team\s+(.+)", choice)
    if match is None:
        raise RecoveryCorpusError(f"unsupported team-preview command: {choice!r}")

    payload = match.group(1).strip()
    if re.fullmatch(r"[1-6]+", payload):
        indices = tuple(int(character) for character in payload)
    elif re.fullmatch(r"[1-6](?:\s*,\s*[1-6])+", payload):
        indices = tuple(
            int(component.strip())
            for component in payload.split(",")
        )
    else:
        raise RecoveryCorpusError(f"unsupported team-preview command: {choice!r}")

    if len(indices) != len(set(indices)):
        raise RecoveryCorpusError(f"invalid team-preview command: {choice!r}")
    return indices


def translate_preview(
    choice: str,
    *,
    source_species: tuple[str, ...],
    target_species: tuple[str, ...],
) -> str:
    indices = _preview_indices(choice)
    source_ids = tuple(_to_id(species) for species in source_species)
    target_ids = tuple(_to_id(species) for species in target_species)
    if len(set(target_ids)) != len(target_ids):
        raise RecoveryCorpusError("cannot translate preview across duplicate species")
    mapped: list[str] = []
    for index in indices:
        wanted = source_ids[index - 1]
        try:
            target_index = target_ids.index(wanted) + 1
        except ValueError as error:
            raise RecoveryCorpusError(
                "preview species are not present in decoy team"
            ) from error
        mapped.append(str(target_index))
    return "team " + "".join(mapped)


def instantiate_exact_battle(
    worker: CorpusWorker,
    validator: TeamValidator,
    *,
    p1: ExactTeamRecord,
    p2: ExactTeamRecord,
    battle_format: str,
    seed: str,
    selector_seed: int,
    cache: dict[tuple[str, str], str] | None = None,
) -> tuple[dict[str, Any], str, str, str, str]:
    p1_text = validate_team_for_battle(
        validator,
        p1,
        battle_format=battle_format,
        cache=cache,
    )
    p2_text = validate_team_for_battle(
        validator,
        p2,
        battle_format=battle_format,
        cache=cache,
    )
    preview_state = worker.create_state(
        battle_format=battle_format,
        p1_team=p1_text,
        p2_team=p2_text,
        seed=seed,
    )
    p1_preview = choose_preview(
        worker,
        state=preview_state,
        side="p1",
        seed_parts=(selector_seed, p1.key, p2.key),
    )
    p2_preview = choose_preview(
        worker,
        state=preview_state,
        side="p2",
        seed_parts=(selector_seed, p1.key, p2.key),
    )
    state = worker.create_state(
        battle_format=battle_format,
        p1_team=p1_text,
        p2_team=p2_text,
        p1_preview=p1_preview,
        p2_preview=p2_preview,
        seed=seed,
    )
    return state, p1_preview, p2_preview, p1_text, p2_text


def _action_family(p1_choice: str, p2_choice: str) -> str:
    def family(choice: str) -> str:
        components = [component.strip() for component in choice.split(",")]
        labels = []
        for component in components:
            if component.startswith("move "):
                labels.append("move")
            elif component.startswith("switch "):
                labels.append("switch")
            elif component in {"pass", "wait"}:
                labels.append("wait")
            else:
                labels.append(component.split(" ", 1)[0] or "other")
        return "+".join(labels)

    return f"p1:{family(p1_choice)}|p2:{family(p2_choice)}"


def _deterministic_choice(
    choices: list[str],
    *,
    action_seed: int,
    battle_index: int,
    turn_number: int,
    side: str,
) -> str | None:
    if not choices:
        return None
    index = _hash_index(
        len(choices),
        action_seed,
        battle_index,
        turn_number,
        side,
    )
    return choices[index]


def _conditioning_batches(
    config: CorpusRunConfig,
    *,
    battle_index: int,
    turn_number: int,
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(
            _sodium_seed(
                "conditioning",
                config.conditioning_seed,
                battle_index,
                turn_number,
                batch,
                slot,
            )
            for slot in range(size)
        )
        for batch, size in enumerate(config.conditioning_batch_sizes)
    )


def _battle_format(
    regulation: str,
    *,
    allow_nonauthoritative: bool,
) -> tuple[str, bool]:
    source = REGULATION_BY_KEY[regulation]
    if source.regulation_validation_authoritative:
        return source.format_id, True
    if not allow_nonauthoritative:
        raise RecoveryCorpusError(
            f"{regulation} has no authoritative historical format in the pin; "
            "omit it or pass --allow-nonauthoritative-regulation"
        )
    return source.validator_format_id, False


def _same_species_decoys(
    records: Iterable[ExactTeamRecord],
    *,
    true_record: ExactTeamRecord,
    max_decoys: int,
    seed_parts: tuple[object, ...],
) -> list[ExactTeamRecord]:
    if max_decoys <= 0:
        return []
    candidates = [
        record
        for record in records
        if record.regulation == true_record.regulation
        and record.key != true_record.key
        and record.canonical_sha256 != true_record.canonical_sha256
        and record.species_signature == true_record.species_signature
    ]
    candidates.sort(
        key=lambda record: _hash_hex(
            *seed_parts,
            record.key,
            record.canonical_sha256,
        )
    )
    return candidates[:max_decoys]


def _instantiate_decoy_worlds(
    worker: CorpusWorker,
    validator: TeamValidator,
    *,
    p2_text: str,
    true_p1: ExactTeamRecord,
    p1_preview: str,
    p2_preview: str,
    candidates: Iterable[ExactTeamRecord],
    battle_format: str,
    battle_seed: str,
    expected_public_view: dict[str, Any],
    previews: dict[str, list[str]],
    cache: dict[tuple[str, str], str],
    battle_index: int,
    diagnostics: dict[str, Any] | None = None,
) -> list[_BattleWorld]:
    wanted = public_observation_signature(expected_public_view)
    worlds: list[_BattleWorld] = []
    candidate_list = list(candidates)
    if diagnostics is not None:
        diagnostics["candidates"] = diagnostics.get("candidates", 0) + len(candidate_list)
    for record in candidate_list:
        try:
            p1_text = validate_team_for_battle(
                validator,
                record,
                battle_format=battle_format,
                cache=cache,
            )
            translated = translate_preview(
                p1_preview,
                source_species=true_p1.species,
                target_species=record.species,
            )
            state = worker.create_state(
                battle_format=battle_format,
                p1_team=p1_text,
                p2_team=p2_text,
                p1_preview=translated,
                p2_preview=p2_preview,
                seed=battle_seed,
            )
            view = worker.state_view(
                state=state,
                side="p2",
                previews=previews,
            )
        except (RecoveryCorpusError, ValueError) as error:
            if diagnostics is not None:
                diagnostics["errors"] = diagnostics.get("errors", 0) + 1
                diagnostics.setdefault("examples", []).append(
                    {
                        "team": record.key,
                        "kind": "error",
                        "detail": str(error),
                    }
                )
                diagnostics["examples"] = diagnostics["examples"][:8]
            continue
        if public_observation_signature(view) != wanted:
            if diagnostics is not None:
                diagnostics["public_mismatches"] = (
                    diagnostics.get("public_mismatches", 0) + 1
                )
                diagnostics.setdefault("examples", []).append(
                    {
                        "team": record.key,
                        "kind": "public-mismatch",
                        "paths": list(
                            public_observation_mismatch_paths(
                                expected_public_view,
                                view,
                            )
                        ),
                    }
                )
                diagnostics["examples"] = diagnostics["examples"][:8]
            continue
        if diagnostics is not None:
            diagnostics["admitted"] = diagnostics.get("admitted", 0) + 1
        worlds.append(
            _BattleWorld(
                record=record,
                state=state,
                world_id=f"decoy:{record.key}",
                history_id=f"battle-{battle_index}:opening:{record.key}",
                p1_lineage=identity_member_lineage(state, "p1"),
                p2_lineage=identity_member_lineage(state, "p2"),
            )
        )
    return worlds

def _increment(
    bucket: dict[str, dict[str, int]],
    key: str,
    *,
    survived: bool,
) -> None:
    item = bucket.setdefault(
        key,
        {"total": 0, "survived": 0, "false_exclusions": 0},
    )
    item["total"] += 1
    if survived:
        item["survived"] += 1
    else:
        item["false_exclusions"] += 1


def _run_id(
    config: CorpusRunConfig,
    pools: TeamPools,
    *,
    showdown_revision: str,
) -> str:
    payload = {
        "schema": RUN_SCHEMA,
        "showdown_revision": showdown_revision,
        "config": config.__dict__,
        "training": [
            (record.key, record.canonical_sha256)
            for record in pools.training
        ],
        "evaluation": [
            (record.key, record.canonical_sha256)
            for record in pools.evaluation
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def run_recovery_corpus(
    worker: CorpusWorker,
    validator: TeamValidator,
    *,
    data_root: str | Path,
    config: CorpusRunConfig = CorpusRunConfig(),
    refresh_pools: bool = False,
) -> CorpusRunResult:
    root = ensure_external_data_root(data_root)
    records = load_exact_team_records(root)
    if not records:
        raise RecoveryCorpusError("team corpus has no exact-ready teams")
    output_root = root / "recovery-soundness"
    shared_pool_path = output_root / "team-pools-v1.json"
    pools = fixed_team_pools(
        records,
        path=shared_pool_path,
        pool_seed=config.pool_seed,
        evaluation_per_regulation=config.evaluation_per_regulation,
        refresh=refresh_pools,
    )
    run_id = _run_id(
        config,
        pools,
        showdown_revision=validator.showdown_revision,
    )
    run_dir = output_root / "runs" / run_id
    cases_path = run_dir / "cases.jsonl"
    summary_path = run_dir / "summary.json"
    pool_path = run_dir / "team-pool.json"
    hard_case_root = run_dir / "hard-cases"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_team_pool_manifest(pools, pool_path)

    validation_cache: dict[tuple[str, str], str] = {}
    reachability_outcomes: list[TrueWorldTransitionOutcome] = []
    conditioning_outcomes: list[TrueWorldConditioningOutcome] = []
    case_rows: list[dict[str, Any]] = []
    reachability_breakdown = {
        "regulation": {},
        "turn": {},
        "action_family": {},
        "rng_class": {},
    }
    conditioning_breakdown = {
        "regulation": {},
        "turn": {},
        "action_family": {},
        "rng_class": {},
    }
    battles_attempted = 0
    battles_completed = 0
    decoy_worlds_created = 0
    decoy_diagnostics: dict[str, Any] = {
        "candidates": 0,
        "admitted": 0,
        "public_mismatches": 0,
        "errors": 0,
        "examples": [],
    }

    all_records = pools.all
    for regulation in config.regulations:
        battle_format, authoritative = _battle_format(
            regulation,
            allow_nonauthoritative=config.allow_nonauthoritative_regulation,
        )
        evaluation = [
            record
            for record in pools.evaluation
            if record.regulation == regulation
        ]
        if not evaluation:
            raise RecoveryCorpusError(
                f"evaluation pool is empty for regulation {regulation}"
            )
        for local_battle in range(config.battles):
            battle_index = battles_attempted
            battles_attempted += 1
            p1 = evaluation[local_battle % len(evaluation)]
            if len(evaluation) == 1:
                p2 = evaluation[0]
            else:
                offset = 1 + _hash_index(
                    len(evaluation) - 1,
                    config.battle_seed,
                    regulation,
                    local_battle,
                    "opponent",
                )
                p2 = evaluation[(local_battle + offset) % len(evaluation)]
                if p2.key == p1.key:
                    p2 = evaluation[(local_battle + 1) % len(evaluation)]

            battle_seed = _sodium_seed(
                "battle",
                config.battle_seed,
                regulation,
                local_battle,
                p1.key,
                p2.key,
            )
            state, p1_preview, p2_preview, p1_text, p2_text = (
                instantiate_exact_battle(
                    worker,
                    validator,
                    p1=p1,
                    p2=p2,
                    battle_format=battle_format,
                    seed=battle_seed,
                    selector_seed=config.battle_seed,
                    cache=validation_cache,
                )
            )

            previews = {
                "p1": list(p1.species),
                "p2": list(p2.species),
            }
            before_view = worker.state_view(
                state=state,
                side="p2",
                previews=previews,
            )
            decoy_records = _same_species_decoys(
                all_records,
                true_record=p1,
                max_decoys=config.max_decoys,
                seed_parts=(
                    config.pool_seed,
                    regulation,
                    local_battle,
                    p1.key,
                ),
            )
            decoys = _instantiate_decoy_worlds(
                worker,
                validator,
                p2_text=p2_text,
                true_p1=p1,
                p1_preview=p1_preview,
                p2_preview=p2_preview,
                candidates=decoy_records,
                battle_format=battle_format,
                battle_seed=battle_seed,
                expected_public_view=before_view,
                previews=previews,
                cache=validation_cache,
                battle_index=battle_index,
                diagnostics=decoy_diagnostics,
            )
            decoy_worlds_created += len(decoys)
            true_world = _BattleWorld(
                record=p1,
                state=state,
                world_id=f"true:{p1.key}",
                history_id=f"battle-{battle_index}:opening:{p1.key}",
                p1_lineage=identity_member_lineage(state, "p1"),
                p2_lineage=identity_member_lineage(state, "p2"),
            )

            completed_turns = 0
            for turn_number in range(1, config.turns + 1):
                p1_choice = _deterministic_choice(
                    worker.legal_choices(
                        state=true_world.state,
                        side="p1",
                    ),
                    action_seed=config.action_seed,
                    battle_index=battle_index,
                    turn_number=turn_number,
                    side="p1",
                )
                p2_choice = _deterministic_choice(
                    worker.legal_choices(
                        state=true_world.state,
                        side="p2",
                    ),
                    action_seed=config.action_seed,
                    battle_index=battle_index,
                    turn_number=turn_number,
                    side="p2",
                )
                if p1_choice is None or p2_choice is None:
                    break
                probe_seed = _sodium_seed(
                    "probe",
                    config.conditioning_seed,
                    battle_index,
                    turn_number,
                )
                case_id = (
                    f"{regulation}-battle-{battle_index:05d}"
                    f"-turn-{turn_number:03d}"
                )
                transition, child = generate_true_world_transition(
                    worker,
                    case_id=case_id,
                    source=f"exact-team-corpus:{regulation}",
                    state=true_world.state,
                    side="p2",
                    p1_choice=p1_choice,
                    p2_choice=p2_choice,
                    actual_rng_seed=None,
                    probe_rng_seed=probe_seed,
                    previous_public_view=before_view,
                    previews=previews,
                )
                reachability_outcome = evaluate_true_world_transition(
                    worker,
                    transition,
                )
                reachability_outcomes.append(reachability_outcome)

                case_decoys = decoys if turn_number == 1 else []
                particles = (true_world.particle(),) + tuple(
                    world.particle()
                    for world in case_decoys
                )
                conditioning_case = TrueWorldConditioningCase(
                    transition=transition,
                    particles=particles,
                    true_world_id=true_world.world_id,
                    rng_batches=_conditioning_batches(
                        config,
                        battle_index=battle_index,
                        turn_number=turn_number,
                    ),
                    max_particles=max(1, len(particles)),
                    resample_seed=int(
                        _hash_hex(
                            config.resample_seed,
                            battle_index,
                            turn_number,
                        )[:8],
                        16,
                    ),
                )
                conditioning_outcome = evaluate_true_world_conditioning(
                    worker,
                    conditioning_case,
                )
                conditioning_outcomes.append(conditioning_outcome)

                action_family = _action_family(p1_choice, p2_choice)
                rng_class = (
                    "zero-rng"
                    if transition.actual_rng_draw_count == 0
                    else "rng-consuming"
                )
                dimensions = (
                    ("regulation", regulation),
                    ("turn", str(turn_number)),
                    ("action_family", action_family),
                    ("rng_class", rng_class),
                )
                for dimension, key in dimensions:
                    _increment(
                        reachability_breakdown[dimension],
                        key,
                        survived=reachability_outcome.survived,
                    )
                    _increment(
                        conditioning_breakdown[dimension],
                        key,
                        survived=conditioning_outcome.survived,
                    )
                case_rows.append(
                    {
                        "case_id": case_id,
                        "regulation": regulation,
                        "battle_format": battle_format,
                        "battle_format_authoritative": authoritative,
                        "battle_index": battle_index,
                        "turn": turn_number,
                        "p1_true_team": p1.key,
                        "p2_ai_team": p2.key,
                        "candidate_worlds": len(particles),
                        "decoy_worlds": len(case_decoys),
                        "p1_choice": p1_choice,
                        "p2_choice": p2_choice,
                        "actual_rng_draw_count": (
                            transition.actual_rng_draw_count
                        ),
                        "action_family": action_family,
                        "rng_class": rng_class,
                        "reachability_status": (
                            reachability_outcome.result.status.value
                        ),
                        "reachability_survived": (
                            reachability_outcome.survived
                        ),
                        "conditioning_survived": (
                            conditioning_outcome.survived
                        ),
                        "conditioning_degraded": (
                            conditioning_outcome.degraded_retention
                        ),
                        "conditioning_generated": (
                            conditioning_outcome.update.generated
                        ),
                        "conditioning_matched": (
                            conditioning_outcome.update.matched
                        ),
                    }
                )

                true_world = _BattleWorld(
                    record=true_world.record,
                    state=child,
                    world_id=true_world.world_id,
                    history_id=(
                        f"{true_world.history_id}:turn-{turn_number}"
                    ),
                    p1_lineage=true_world.p1_lineage,
                    p2_lineage=true_world.p2_lineage,
                )
                before_view = transition.actual_public_view
                completed_turns += 1

            if completed_turns:
                battles_completed += 1

    reachability_report = RecoverySoundnessReport(
        outcomes=tuple(reachability_outcomes)
    )
    conditioning_report = ConditioningSoundnessReport(
        outcomes=tuple(conditioning_outcomes)
    )
    write_false_exclusion_regressions(
        reachability_report,
        output_dir=hard_case_root / "reachability",
    )
    write_conditioning_false_exclusion_regressions(
        conditioning_report,
        output_dir=hard_case_root / "conditioning",
    )
    _atomic_write_text(
        cases_path,
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in case_rows
        ),
    )
    summary = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "showdown_revision": validator.showdown_revision,
        "config": config.__dict__,
        "pool_manifest": str(pool_path),
        "shared_pool_manifest": str(shared_pool_path),
        "battles_attempted": battles_attempted,
        "battles_completed": battles_completed,
        "transitions": len(case_rows),
        "decoy_worlds_created": decoy_worlds_created,
        "decoy_diagnostics": decoy_diagnostics,
        "reachability": reachability_report.summary(),
        "conditioning": conditioning_report.summary(),
        "breakdown": {
            "reachability": reachability_breakdown,
            "conditioning": conditioning_breakdown,
        },
    }
    _atomic_write_text(
        summary_path,
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
    )
    _atomic_write_text(
        output_root / "latest-summary.json",
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
    )
    return CorpusRunResult(
        run_id=run_id,
        run_dir=run_dir,
        summary_path=summary_path,
        cases_path=cases_path,
        pool_path=pool_path,
        reachability=reachability_report,
        conditioning=conditioning_report,
        summary=summary,
    )


def _resolve_data_root(value: str | None) -> Path:
    selected = value or os.environ.get(DATA_ROOT_ENV)
    if not selected:
        raise RecoveryCorpusError(
            f"Pass --data-root or set {DATA_ROOT_ENV}. "
            "The Windows launcher supplies the local F: drive default."
        )
    return Path(selected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic exact-team recovery soundness measurement."
        )
    )
    parser.add_argument(
        "--data-root",
        help=f"External corpus root; or set {DATA_ROOT_ENV}.",
    )
    parser.add_argument(
        "--regulations",
        nargs="+",
        choices=tuple(REGULATION_BY_KEY),
        default=["mc"],
        help="Battle regulations to measure; defaults to current M-C.",
    )
    parser.add_argument("--battles", type=int, default=DEFAULT_BATTLES)
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument(
        "--max-decoys",
        type=int,
        default=DEFAULT_MAX_DECOYS,
    )
    parser.add_argument(
        "--evaluation-per-regulation",
        type=int,
        default=DEFAULT_EVALUATION_PER_REGULATION,
    )
    parser.add_argument(
        "--pool-seed",
        type=int,
        default=DEFAULT_POOL_SEED,
    )
    parser.add_argument(
        "--battle-seed",
        type=int,
        default=DEFAULT_BATTLE_SEED,
    )
    parser.add_argument(
        "--action-seed",
        type=int,
        default=DEFAULT_ACTION_SEED,
    )
    parser.add_argument(
        "--conditioning-seed",
        type=int,
        default=DEFAULT_CONDITIONING_SEED,
    )
    parser.add_argument(
        "--resample-seed",
        type=int,
        default=DEFAULT_RESAMPLE_SEED,
    )
    parser.add_argument(
        "--conditioning-batches",
        nargs="+",
        type=int,
        default=list(DEFAULT_CONDITIONING_BATCH_SIZES),
        help="Adaptive conditioning batch sizes; production defaults to 2 then 4.",
    )
    parser.add_argument(
        "--refresh-pools",
        action="store_true",
        help="Replace the fixed external train/evaluation pool manifest.",
    )
    parser.add_argument(
        "--allow-nonauthoritative-regulation",
        action="store_true",
        help=(
            "Permit historical regulations lacking an exact format in the pin "
            "(currently M-A)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = CorpusRunConfig(
            regulations=tuple(args.regulations),
            battles=args.battles,
            turns=args.turns,
            max_decoys=args.max_decoys,
            conditioning_batch_sizes=tuple(args.conditioning_batches),
            pool_seed=args.pool_seed,
            evaluation_per_regulation=(
                args.evaluation_per_regulation
            ),
            battle_seed=args.battle_seed,
            action_seed=args.action_seed,
            conditioning_seed=args.conditioning_seed,
            resample_seed=args.resample_seed,
            allow_nonauthoritative_regulation=(
                args.allow_nonauthoritative_regulation
            ),
        )
        data_root = _resolve_data_root(args.data_root)
        with (
            TeamValidationWorker() as validator,
            HypotheticalSearchWorker() as worker,
        ):
            result = run_recovery_corpus(
                worker,
                validator,
                data_root=data_root,
                config=config,
                refresh_pools=args.refresh_pools,
            )
        print(json.dumps(result.summary, indent=2))
    except (RecoveryCorpusError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
