"""Command-line entry point for the practice bot."""

from champions_practice.config import CHAMPIONS_FORMAT, SHOWDOWN_WS_URL


def main() -> None:
    print("Champions Practice Bot")
    print(f"Format:   {CHAMPIONS_FORMAT}")
    print(f"Showdown: {SHOWDOWN_WS_URL}")
    print()
    print("Persistent public-belief battle controller is installed.")
    print("Interactive battle UI is the next milestone.")


if __name__ == "__main__":
    main()
