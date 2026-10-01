"""Flag monthly indicator observations beyond a prior-12-month z-score of 2.5."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("[anomaly] Install dependencies: python -m pip install -r requirements.txt") from exc

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.clean import PROC_DIR
from src.etl.load_duckdb import DUCKDB_PATH


MONTHLY_CODES = ("BRENT", "GOLD", "EURTND", "USDTND", "WHEAT")
COLUMNS = ["date", "indicator_code", "value", "zscore", "is_anomaly"]


def rolling_anomalies(series: pd.DataFrame, window: int = 12,
                      threshold: float = 2.5) -> pd.DataFrame:
    """Score each value against its previous 12 observed monthly values."""
    if window < 3 or threshold <= 0:
        raise ValueError("[anomaly] window must be >=3 and threshold positive")
    frame = series[["date", "indicator_code", "value"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    prior_mean = frame["value"].rolling(window, min_periods=window).mean().shift(1)
    prior_std = frame["value"].rolling(window, min_periods=window).std().shift(1)
    # A perfectly flat prior window still makes a new nonzero move unusual.
    frame["zscore"] = ((frame["value"] - prior_mean) /
                        prior_std.where(prior_std > 0, 1e-9)).astype(float)
    frame["is_anomaly"] = frame["zscore"].abs().gt(threshold).fillna(False)
    return frame[COLUMNS]


def detect_all(db_path: Path = DUCKDB_PATH, proc_dir: Path = PROC_DIR) -> pd.DataFrame:
    """Load monthly observations from DuckDB and write anomalies.parquet."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("[anomaly] Install DuckDB: python -m pip install duckdb") from exc
    db_path, proc_dir = Path(db_path), Path(proc_dir)
    if not db_path.is_file():
        raise FileNotFoundError(f"[anomaly] Missing {db_path}; run load_duckdb first")
    with duckdb.connect(str(db_path), read_only=True) as connection:
        observations = connection.execute("""
            SELECT date, indicator_code, value FROM fact_indicators
            ORDER BY indicator_code, date
        """).df()
    frames = []
    for code in MONTHLY_CODES:
        sample = observations.loc[observations["indicator_code"] == code]
        if sample.empty:
            print(f"[anomaly] WARNING {code}: no observations; skipping")
            continue
        scored = rolling_anomalies(sample)
        print(f"[anomaly] {code}: {int(scored['is_anomaly'].sum())} flagged of {len(scored)}")
        frames.append(scored)
    print("[anomaly] CPI skipped: its source is annual, not monthly")
    result = (pd.concat(frames, ignore_index=True) if frames else
              pd.DataFrame(columns=COLUMNS))
    proc_dir.mkdir(parents=True, exist_ok=True)
    result.to_parquet(proc_dir / "anomalies.parquet", index=False)
    print(f"[anomaly] saved anomalies.parquet ({len(result)} rows)")
    return result


def main() -> None:
    """Run standalone anomaly detection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DUCKDB_PATH)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    arguments = parser.parse_args()
    try:
        detect_all(arguments.db_path, arguments.proc_dir)
    except RuntimeError as exc:
        print(exc)
        raise SystemExit(1) from exc
    except ImportError as exc:
        raise SystemExit("[anomaly] Install Parquet support: python -m pip install pyarrow") from exc


if __name__ == "__main__":
    main()
