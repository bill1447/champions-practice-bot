"""CLI for semantic-policy aliases, post-hoc evaluation, and comparisons."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from champions_practice.replay_corpus import DATA_ROOT_ENV, DEFAULT_FORMAT
from champions_practice.semantic_policy_diagnostics import (
    compare_training_runs,
    evaluate_saved_training,
    format_comparison_table,
)
from champions_practice.semantic_policy_registry import (
    SemanticPolicyRegistryError,
    alias_snapshot,
    register_dataset_alias,
    register_training_alias,
)
from champions_practice.semantic_policy_train import SemanticPolicyTrainingError


def _resolve_data_root(value: str | None) -> Path:
    selected = value or os.environ.get(DATA_ROOT_ENV)
    if not selected:
        raise SemanticPolicyTrainingError(f"Pass --data-root or set {DATA_ROOT_ENV}.")
    return Path(selected)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage aliases and diagnostics for saved semantic-policy runs."
    )
    parser.add_argument("--data-root")
    parser.add_argument("--format", default=DEFAULT_FORMAT, dest="format_id")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dataset_alias = subparsers.add_parser(
        "alias-dataset",
        help="Bind a human-readable alias to an immutable semantic-audit run.",
    )
    dataset_alias.add_argument("alias")
    dataset_alias.add_argument("run_id")

    training_alias = subparsers.add_parser(
        "alias-training",
        help="Bind a human-readable alias to an immutable training run.",
    )
    training_alias.add_argument("alias")
    training_alias.add_argument("training_id")
    training_alias.add_argument("--dataset", required=True)

    evaluate = subparsers.add_parser(
        "evaluate",
        help="Re-evaluate a saved model without retraining it.",
    )
    evaluate.add_argument("training")
    evaluate.add_argument("--dataset")

    compare = subparsers.add_parser(
        "compare",
        help="Print a compact comparison across two or more saved runs.",
    )
    compare.add_argument("training", nargs="+")
    compare.add_argument("--json", action="store_true")

    subparsers.add_parser("aliases", help="Print the alias registry.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    try:
        data_root = _resolve_data_root(args.data_root)
        if args.command == "alias-dataset":
            result = register_dataset_alias(
                data_root,
                alias=args.alias,
                run_id=args.run_id,
                format_id=args.format_id,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.command == "alias-training":
            result = register_training_alias(
                data_root,
                alias=args.alias,
                training_id=args.training_id,
                dataset_reference=args.dataset,
                format_id=args.format_id,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.command == "evaluate":
            result = evaluate_saved_training(
                data_root,
                args.training,
                dataset_reference=args.dataset,
                format_id=args.format_id,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.command == "compare":
            if len(args.training) < 2:
                raise SemanticPolicyTrainingError(
                    "comparison requires at least two training runs"
                )
            rows = compare_training_runs(
                data_root,
                list(args.training),
                format_id=args.format_id,
            )
            if args.json:
                print(json.dumps(rows, indent=2, sort_keys=True))
            else:
                print(format_comparison_table(rows))
            return
        if args.command == "aliases":
            print(json.dumps(alias_snapshot(data_root), indent=2, sort_keys=True))
            return
        raise SemanticPolicyTrainingError(f"unsupported command {args.command!r}")
    except (
        SemanticPolicyRegistryError,
        SemanticPolicyTrainingError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
