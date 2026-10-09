"""Pinned Showdown smoke: independent oracle and public-only real-league challenge.

This is a *transport and evidence-boundary* smoke, NOT a recovery-success
claim: only one live decision is allowed and the real historical collapses
occur much later. A full local --run-games 2,8 is the real challenge.
"""

from champions_practice.rebase_challenge import run_case


def main() -> None:
    result = run_case(1, max_decisions=1)
    assert result["game_number"] == 2
    assert result["turns_attempted"] == 1
    row = result["all_turns"][0]
    if not row["oracle_valid"]:
        raise SystemExit(
            "ERROR: independent oracle diverges from the actual league public state"
        )
    if row["status"] == "POSITIVE_CHECKPOINT" and row["verified_current_states"] < 1:
        raise SystemExit("ERROR: checkpoint claim lacks validated Showdown state")
    if row.get("live_admission_authorized") is not False:
        raise SystemExit("ERROR: diagnostic reconstruction granted live admission")
    print("RESULT: one-turn league/oracle/public-rebase evidence boundary passed")
    print("Historical turn-eight Protect/Wood Hammer success: NOT TESTED by this smoke")
    print(f"First-turn checkpoint status: {row['status']}")


if __name__ == "__main__":
    main()
