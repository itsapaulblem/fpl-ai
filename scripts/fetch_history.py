"""Download vaastav historical seasons into data/external/vaastav/."""
from __future__ import annotations

import argparse

from src.historical import download_vaastav_season

DEFAULT_SEASONS = ["2022-23", "2023-24", "2024-25"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download vaastav historical FPL data")
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS,
                        help="Seasons to download (e.g. 2022-23 2023-24)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if cached files exist")
    args = parser.parse_args()

    for season in args.seasons:
        print(f"[fetch] {season} ...", flush=True)
        paths = download_vaastav_season(season, force=args.force)
        for key, path in paths.items():
            size_kb = path.stat().st_size / 1024
            print(f"        {key:<8} -> {path.name} ({size_kb:,.0f} KB)")
    print("done.")


if __name__ == "__main__":
    main()
