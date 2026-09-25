"""Record provenance for the ignored/generated Pokemon Showdown dist tree."""

from champions_practice.search_worker import write_showdown_build_stamp


def main() -> None:
    stamp = write_showdown_build_stamp()
    print(
        "Pokemon Showdown build stamped: "
        f"{stamp['source_sha']} / {stamp['dist_sha256']}"
    )


if __name__ == "__main__":
    main()
