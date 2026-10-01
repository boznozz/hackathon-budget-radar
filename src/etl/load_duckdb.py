"""Load cleaned and star Parquet data into the analytical DuckDB database."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.clean import PROC_DIR, PROJECT_ROOT, RAW_DIR


DUCKDB_PATH = PROJECT_ROOT / "data" / "budget.duckdb"
STAR_TABLES = ("dim_time", "dim_indicator", "fact_indicators", "fact_budget", "dim_shock")


def table_names(raw_dir: Path = RAW_DIR) -> list[str]:
    """List cleaned raw names plus star tables, excluding model artifacts."""
    raw_names = {path.stem for path in Path(raw_dir).iterdir()
                 if path.suffix.lower() in {".csv", ".json"}}
    return sorted(raw_names | set(STAR_TABLES))


def load_duckdb(proc_dir: Path = PROC_DIR, db_path: Path = DUCKDB_PATH,
                raw_dir: Path = RAW_DIR) -> dict[str, int]:
    """Atomically replace available analytical tables and print sanity ranges."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("[load_duckdb] Install DuckDB: python -m pip install duckdb") from exc
    proc_dir, db_path = Path(proc_dir), Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with duckdb.connect(str(db_path)) as connection:
        connection.begin()
        try:
            for name in table_names(raw_dir):
                path = proc_dir / f"{name}.parquet"
                if not path.is_file():
                    print(f"[load_duckdb] WARNING missing {path.name}; skipping")
                    continue
                connection.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_parquet(?)",
                                   [str(path.resolve())])
                count = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                counts[name] = count
                columns = {row[1] for row in connection.execute(f"PRAGMA table_info('{name}')").fetchall()}
                date_range = (connection.execute(f"SELECT min(date), max(date) FROM {name}").fetchone()
                              if "date" in columns else None)
                print(f"[load_duckdb] {name}: {count} rows"
                      + (f", dates {date_range[0]} to {date_range[1]}" if date_range else ""))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return counts


def main() -> None:
    """Run the standalone DuckDB loading stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    parser.add_argument("--db-path", type=Path, default=DUCKDB_PATH)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    arguments = parser.parse_args()
    try:
        load_duckdb(arguments.proc_dir, arguments.db_path, arguments.raw_dir)
    except RuntimeError as exc:
        print(exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
