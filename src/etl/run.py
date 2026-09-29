"""Run the raw CSV -> cleaned Parquet -> star schema -> DuckDB ETL."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.build_star import build_star
from src.etl.clean import PROC_DIR, RAW_DIR, clean_all
from src.etl.load_duckdb import DUCKDB_PATH, load_duckdb


def main() -> None:
    """Run all three ETL stages with compatible paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=PROC_DIR)
    parser.add_argument("--db-path", type=Path, default=DUCKDB_PATH)
    args = parser.parse_args()
    clean_all(args.raw_dir, args.processed_dir)
    build_star(args.processed_dir)
    load_duckdb(args.processed_dir, args.db_path, args.raw_dir)
    print(f"[etl.run] database: {args.db_path}")


if __name__ == "__main__":
    main()
