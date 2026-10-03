"""Integration smoke for pinned-Showdown team-corpus validation."""

from __future__ import annotations

import json

from champions_practice.search_worker import TeamValidationWorker
from champions_practice.teams import SMOKE_TEAM


def main() -> None:
    with TeamValidationWorker() as validator:
        result = validator.validate_team(
            battle_format="gen9championsvgc2026regmc",
            team_text=SMOKE_TEAM,
        )
        revision = validator.showdown_revision

    if result["valid"] is not True:
        raise RuntimeError(
            "Pinned Showdown rejected the integration team: "
            + "; ".join(result["problems"])
        )
    if result["team_size"] != 6:
        raise RuntimeError("Pinned Showdown returned the wrong team size")
    if len(result["sets"]) != 6:
        raise RuntimeError("Pinned Showdown returned the wrong structured set count")
    if "Indeedee-F" not in result["canonical_text"]:
        raise RuntimeError("Pinned Showdown canonical export lost the integration team")

    print(
        json.dumps(
            {
                "showdown_revision": revision,
                "valid": result["valid"],
                "team_size": result["team_size"],
                "canonical_bytes": len(
                    result["canonical_text"].encode("utf-8")
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
