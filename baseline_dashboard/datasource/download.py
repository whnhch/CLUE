"""
download.py
-----------
Fetch the raw jaffle-shop CSVs the build reads (~546 MB).

Run from the baseline_dashboard directory:

    python -m datasource.download          # fetch whatever is missing
    python -m datasource.download --force  # re-fetch everything

`python -m datasource.build` calls this first, so a fresh clone needs only the
build command. Running it on its own is for fetching ahead of time.

The source is dbt Labs' public six-year jaffle-shop dataset -- the
`long_term_dataset` used by the dbt quickstarts, not the one-year seeds in the
jaffle-shop repo. The build's time shift and synthesis constants were tuned on
this exact export, so the expected size of every file is pinned: a file
already on disk at that size is skipped without touching the network, and a
download that comes back a different size fails rather than building the
dashboard from different data.
"""

import argparse
import urllib.request
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data"

BASE_URL = "https://dbt-tutorial-public.s3.amazonaws.com/long_term_dataset"

# File name -> size in bytes.
RAW_FILES: dict[str, int] = {
    "raw_customers.csv": 159_115,
    "raw_orders.csv": 297_899_240,
    "raw_order_items.csv": 247_985_646,
    "raw_products.csv": 912,
    "raw_supplies.csv": 2_589,
    "raw_stores.csv": 470,
}

CHUNK_BYTES = 1 << 20


def _log(message: str, end: str = "\n") -> None:
    print(message, end=end, flush=True)


def is_present(name: str) -> bool:
    """True when the file is on disk at its pinned size."""
    path = RAW_DIR / name
    return path.exists() and path.stat().st_size == RAW_FILES[name]


def missing_files() -> list[str]:
    return [name for name in RAW_FILES if not is_present(name)]


def fetch(name: str) -> None:
    """
    Download one file.

    Writes to a `.part` file and renames on success, so an interrupted
    download is never mistaken for a complete one.
    """
    expected = RAW_FILES[name]
    target = RAW_DIR / name
    partial = target.with_name(target.name + ".part")

    received = 0
    next_report = 0.1
    with urllib.request.urlopen(f"{BASE_URL}/{name}") as response, partial.open(
        "wb"
    ) as out:
        while chunk := response.read(CHUNK_BYTES):
            out.write(chunk)
            received += len(chunk)
            if expected > 10 * CHUNK_BYTES and received / expected >= next_report:
                _log(f"\r  {name}  {received / expected:4.0%}", end="")
                next_report += 0.1

    if received != expected:
        partial.unlink()
        raise RuntimeError(
            f"{name}: expected {expected:,} bytes, got {received:,}. The "
            "upstream dataset may have changed; the build is tuned to the "
            "pinned export."
        )

    partial.replace(target)
    _log(f"\r  {name}  {received / 1e6:,.1f} MB")


def ensure_raw_data(force: bool = False) -> None:
    """Download any raw file that is missing or the wrong size."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    names = list(RAW_FILES) if force else missing_files()
    if not names:
        return

    total = sum(RAW_FILES[name] for name in names) / 1e6
    _log(f"Downloading {len(names)} raw jaffle-shop file(s), {total:,.0f} MB...")
    for name in names:
        fetch(name)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch the raw jaffle-shop CSVs into data/."
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download files already present"
    )
    args = parser.parse_args(argv)

    ensure_raw_data(force=args.force)
    _log(f"Raw data ready in {RAW_DIR}")


if __name__ == "__main__":
    main()
