"""Tiny deterministic exact-team recovery corpus smoke for CI."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.recovery_corpus import CorpusRunConfig, run_recovery_corpus
from champions_practice.search_worker import (
    HypotheticalSearchWorker,
    TeamValidationWorker,
)
from champions_practice.teams import SMOKE_TEAM


# Keep the opening public state mechanically identical while changing hidden
# set truth.  A move difference cannot activate or reveal itself during team
# preview/opening, unlike items/abilities that may have switch-in effects.
VARIANT_TEAM = SMOKE_TEAM.replace(
    "- Rock Slide",
    "- Feint",
    1,
)


def _install_team(
    connection: sqlite3.Connection,
    *,
    root: Path,
    team_id: str,
    validation: dict,
    revision: str,
) -> None:
    canonical = validation["canonical_text"].encode("utf-8")
    relative = Path("teams") / "canonical" / "mc" / team_id / "team.txt"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical)
    digest = hashlib.sha256(canonical).hexdigest()
    species = [
        team_set["species"]
        for team_set in validation["sets"]
    ]
    connection.execute(
        """
        INSERT INTO teams (
            regulation, team_id, format_id, validator_format_id,
            regulation_validation_authoritative, canonical_relative_path,
            canonical_sha256, packed_team, sets_json, species_json,
            validator_revision, exact_team_ready, validation_state
        )
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 1, 'valid')
        """,
        (
            "mc",
            team_id,
            CHAMPIONS_FORMAT,
            CHAMPIONS_FORMAT,
            relative.as_posix(),
            digest,
            validation["packed_team"],
            json.dumps(validation["sets"]),
            json.dumps(species),
            revision,
        ),
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="champions-recovery-corpus-") as temp:
        root = Path(temp)
        database = root / "teams" / "manifests" / "teams.sqlite3"
        database.parent.mkdir(parents=True, exist_ok=True)

        with (
            TeamValidationWorker() as validator,
            HypotheticalSearchWorker() as worker,
        ):
            validations = [
                validator.validate_team(
                    battle_format=CHAMPIONS_FORMAT,
                    team_text=team_text,
                )
                for team_text in (SMOKE_TEAM, VARIANT_TEAM)
            ]
            if not all(result["valid"] for result in validations):
                raise SystemExit(
                    "ERROR: recovery corpus smoke fixture team failed validation"
                )

            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TABLE teams (
                        regulation TEXT NOT NULL,
                        team_id TEXT NOT NULL,
                        format_id TEXT NOT NULL,
                        validator_format_id TEXT NOT NULL,
                        regulation_validation_authoritative INTEGER NOT NULL,
                        canonical_relative_path TEXT,
                        canonical_sha256 TEXT,
                        packed_team TEXT,
                        sets_json TEXT,
                        species_json TEXT,
                        validator_revision TEXT,
                        exact_team_ready INTEGER NOT NULL,
                        validation_state TEXT NOT NULL,
                        PRIMARY KEY (regulation, team_id)
                    )
                    """
                )
                for index, validation in enumerate(validations, start=1):
                    _install_team(
                        connection,
                        root=root,
                        team_id=f"fixture-{index}",
                        validation=validation,
                        revision=validator.showdown_revision,
                    )
                connection.commit()
            finally:
                connection.close()

            result = run_recovery_corpus(
                worker,
                validator,
                data_root=root,
                config=CorpusRunConfig(
                    regulations=("mc",),
                    battles=1,
                    turns=2,
                    max_decoys=1,
                    conditioning_batch_sizes=(2, 4),
                    evaluation_per_regulation=2,
                ),
                refresh_pools=True,
            )

        if result.summary["transitions"] < 1:
            raise SystemExit(
                "ERROR: recovery corpus smoke generated no transitions"
            )
        if result.summary["decoy_worlds_created"] < 1:
            raise SystemExit(
                "ERROR: recovery corpus smoke did not instantiate a decoy world"
            )
        if result.reachability.false_exclusions:
            raise SystemExit(
                "ERROR: recovery corpus smoke reachability excluded true world"
            )
        if result.conditioning.false_exclusions:
            raise SystemExit(
                "ERROR: recovery corpus smoke conditioning excluded true world"
            )
        if (
            not result.summary_path.is_file()
            or not result.cases_path.is_file()
            or not result.pool_path.is_file()
        ):
            raise SystemExit(
                "ERROR: recovery corpus smoke did not persist external reports"
            )

        print("PASS: deterministic exact-team recovery corpus smoke")
        print(json.dumps(result.summary["reachability"], indent=2))
        print(json.dumps(result.summary["conditioning"], indent=2))


if __name__ == "__main__":
    main()
