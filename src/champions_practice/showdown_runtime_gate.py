"""Verify the local Pokemon Showdown runtime matches the repository pin."""

from champions_practice.search_worker import verify_showdown_checkout


def main() -> None:
    revision = verify_showdown_checkout()
    print(f"Pokemon Showdown runtime verified: {revision}")


if __name__ == "__main__":
    main()
