"""Human-readable aliases for immutable semantic-policy run identifiers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from champions_practice.replay_corpus import (
    DEFAULT_FORMAT,
    _validate_public_id,
    initialize_layout,
)

ALIAS_SCHEMA = "semantic-policy-alias-registry-v1"


class SemanticPolicyRegistryError(RuntimeError):
    """Alias metadata is missing, stale, or attempts to rebind a name."""


def _registry_path(data_root: str | Path) -> Path:
    layout = initialize_layout(data_root)
    return layout.models / "semantic-policy" / "aliases.json"


def _empty_registry() -> dict[str, Any]:
    return {
        "schema": ALIAS_SCHEMA,
        "dataset_aliases": {},
        "training_aliases": {},
    }


def _load_registry(data_root: str | Path) -> dict[str, Any]:
    path = _registry_path(data_root)
    if not path.is_file():
        return _empty_registry()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != ALIAS_SCHEMA:
        raise SemanticPolicyRegistryError(f"unsupported alias registry at {path}")
    for key in ("dataset_aliases", "training_aliases"):
        if not isinstance(payload.get(key), dict):
            raise SemanticPolicyRegistryError(f"alias registry has invalid {key}")
    return payload


def _write_registry(data_root: str | Path, payload: dict[str, Any]) -> None:
    path = _registry_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validated_reference(value: str, *, label: str) -> str:
    try:
        return _validate_public_id(value, label=label)
    except ValueError as error:
        raise SemanticPolicyRegistryError(str(error)) from error


def resolve_dataset_reference(
    data_root: str | Path,
    reference: str,
    *,
    format_id: str = DEFAULT_FORMAT,
) -> str:
    """Resolve a dataset hash or human alias without changing provenance."""
    reference = _validated_reference(reference, label="dataset run or alias")
    format_id = _validated_reference(format_id, label="format")
    layout = initialize_layout(data_root)
    direct = (
        layout.processed
        / "replay-policy"
        / format_id
        / "runs"
        / reference
        / "summary.json"
    )
    if direct.is_file():
        return reference

    registry = _load_registry(data_root)
    entry = registry["dataset_aliases"].get(reference)
    if not isinstance(entry, dict):
        raise SemanticPolicyRegistryError(
            f"unknown dataset run or alias {reference!r} for {format_id}"
        )
    if entry.get("format_id") != format_id:
        raise SemanticPolicyRegistryError(
            f"dataset alias {reference!r} belongs to {entry.get('format_id')!r}, "
            f"not {format_id!r}"
        )
    run_id = entry.get("run_id")
    if not isinstance(run_id, str):
        raise SemanticPolicyRegistryError(f"dataset alias {reference!r} is malformed")
    target = (
        layout.processed
        / "replay-policy"
        / format_id
        / "runs"
        / run_id
        / "summary.json"
    )
    if not target.is_file():
        raise SemanticPolicyRegistryError(
            f"dataset alias {reference!r} points to missing run {run_id!r}"
        )
    return run_id


def register_dataset_alias(
    data_root: str | Path,
    *,
    alias: str,
    run_id: str,
    format_id: str = DEFAULT_FORMAT,
) -> dict[str, str]:
    alias = _validated_reference(alias, label="dataset alias")
    run_id = resolve_dataset_reference(data_root, run_id, format_id=format_id)
    registry = _load_registry(data_root)
    entry = {"format_id": format_id, "run_id": run_id}
    existing = registry["dataset_aliases"].get(alias)
    if existing is not None and existing != entry:
        raise SemanticPolicyRegistryError(
            f"dataset alias {alias!r} is already bound to {existing}"
        )
    if existing is None:
        registry["dataset_aliases"][alias] = entry
        _write_registry(data_root, registry)
    return entry


def _training_report_path(
    data_root: str | Path,
    *,
    dataset_run_id: str,
    training_id: str,
) -> Path:
    layout = initialize_layout(data_root)
    return (
        layout.models
        / "semantic-policy"
        / dataset_run_id
        / training_id
        / "report.json"
    )


def resolve_training_reference(
    data_root: str | Path,
    reference: str,
    *,
    dataset_reference: str | None = None,
    format_id: str = DEFAULT_FORMAT,
) -> dict[str, Any]:
    """Resolve a training hash or alias to its immutable report."""
    reference = _validated_reference(reference, label="training run or alias")
    registry = _load_registry(data_root)
    alias_entry = registry["training_aliases"].get(reference)
    if isinstance(alias_entry, dict):
        dataset_run_id = alias_entry.get("dataset_run_id")
        training_id = alias_entry.get("training_id")
        if not isinstance(dataset_run_id, str) or not isinstance(training_id, str):
            raise SemanticPolicyRegistryError(
                f"training alias {reference!r} is malformed"
            )
        path = _training_report_path(
            data_root,
            dataset_run_id=dataset_run_id,
            training_id=training_id,
        )
        if not path.is_file():
            raise SemanticPolicyRegistryError(
                f"training alias {reference!r} points to a missing report"
            )
        return {
            "reference": reference,
            "dataset_run_id": dataset_run_id,
            "training_id": training_id,
            "report_path": path,
        }

    if dataset_reference is not None:
        dataset_run_id = resolve_dataset_reference(
            data_root,
            dataset_reference,
            format_id=format_id,
        )
        path = _training_report_path(
            data_root,
            dataset_run_id=dataset_run_id,
            training_id=reference,
        )
        if not path.is_file():
            raise SemanticPolicyRegistryError(
                f"training run {reference!r} does not exist under dataset "
                f"{dataset_run_id!r}"
            )
        return {
            "reference": reference,
            "dataset_run_id": dataset_run_id,
            "training_id": reference,
            "report_path": path,
        }

    layout = initialize_layout(data_root)
    matches = sorted(
        (layout.models / "semantic-policy").glob(f"*/{reference}/report.json")
    )
    if not matches:
        raise SemanticPolicyRegistryError(
            f"unknown training run or alias {reference!r}"
        )
    if len(matches) > 1:
        raise SemanticPolicyRegistryError(
            f"training id {reference!r} exists under multiple datasets; "
            "provide a dataset reference"
        )
    path = matches[0]
    return {
        "reference": reference,
        "dataset_run_id": path.parent.parent.name,
        "training_id": reference,
        "report_path": path,
    }


def register_training_alias(
    data_root: str | Path,
    *,
    alias: str,
    training_id: str,
    dataset_reference: str,
    format_id: str = DEFAULT_FORMAT,
) -> dict[str, str]:
    alias = _validated_reference(alias, label="training alias")
    resolved = resolve_training_reference(
        data_root,
        training_id,
        dataset_reference=dataset_reference,
        format_id=format_id,
    )
    entry = {
        "dataset_run_id": resolved["dataset_run_id"],
        "training_id": resolved["training_id"],
    }
    registry = _load_registry(data_root)
    existing = registry["training_aliases"].get(alias)
    if existing is not None and existing != entry:
        raise SemanticPolicyRegistryError(
            f"training alias {alias!r} is already bound to {existing}"
        )
    if existing is None:
        registry["training_aliases"][alias] = entry
        _write_registry(data_root, registry)
    return entry


def alias_snapshot(data_root: str | Path) -> dict[str, Any]:
    return _load_registry(data_root)


def preferred_dataset_alias(data_root: str | Path, run_id: str) -> str | None:
    registry = _load_registry(data_root)
    matches = sorted(
        alias
        for alias, entry in registry["dataset_aliases"].items()
        if isinstance(entry, dict) and entry.get("run_id") == run_id
    )
    return matches[0] if matches else None


def preferred_training_alias(data_root: str | Path, training_id: str) -> str | None:
    registry = _load_registry(data_root)
    matches = sorted(
        alias
        for alias, entry in registry["training_aliases"].items()
        if isinstance(entry, dict) and entry.get("training_id") == training_id
    )
    return matches[0] if matches else None
