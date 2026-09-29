"""Run Prophet forecasts, anomaly detection, and the implied budget scenario."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.clean import PROC_DIR
from src.etl.load_duckdb import DUCKDB_PATH
from src.models.anomaly import detect_all
from src.models.forecast import forecast_all


def run_models(db_path: Path = DUCKDB_PATH, proc_dir: Path = PROC_DIR) -> None:
    """Rebuild model outputs in the required order."""
    forecast_all(db_path, proc_dir)
    detect_all(db_path, proc_dir)


def main() -> None:
    """Run the model stages from one standalone command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DUCKDB_PATH)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    arguments = parser.parse_args()
    run_models(arguments.db_path, arguments.proc_dir)
    print("[models.run] Forecast and anomaly outputs updated. Run scenario.py to inspect impacts.")


if __name__ == "__main__":
    main()
