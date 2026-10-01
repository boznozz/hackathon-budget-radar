"""Fit monthly Prophet series and save six-month indicator forecasts."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("[forecast] Install dependencies: python -m pip install -r requirements.txt") from exc

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.clean import PROC_DIR
from src.etl.load_duckdb import DUCKDB_PATH


FORECAST_CODES = ("BRENT", "GOLD", "EURTND", "USDTND", "WHEAT", "CPI")


def load_history(db_path: Path, code: str) -> pd.DataFrame:
    """Read a single indicator from DuckDB for analytical modeling."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("[forecast] Install DuckDB: python -m pip install duckdb") from exc
    with duckdb.connect(str(db_path), read_only=True) as connection:
        frame = connection.execute("""
            SELECT date AS ds, value AS y
            FROM fact_indicators WHERE indicator_code = ?
            ORDER BY date
        """, [code]).df()
    return frame.dropna().drop_duplicates("ds", keep="last").reset_index(drop=True)


def is_monthly(history: pd.DataFrame) -> bool:
    """Require mostly monthly observations before fitting monthly seasonality."""
    if len(history) < 18:
        return False
    dates = pd.to_datetime(history["ds"])
    span = (dates.max().year - dates.min().year) * 12 + dates.max().month - dates.min().month + 1
    return dates.dt.to_period("M").nunique() == len(dates) and len(dates) / span >= 0.7


def forecast_one(history: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Fit Prophet and return six future months plus in-sample residual std."""
    try:
        from prophet import Prophet
    except ImportError as exc:
        raise RuntimeError("[forecast] Install Prophet: python -m pip install prophet") from exc
    model = Prophet(yearly_seasonality=True, weekly_seasonality=False,
                    daily_seasonality=False, uncertainty_samples=100)
    model.fit(history[["ds", "y"]])
    fitted = model.predict(history[["ds"]])
    residual_std = float((history["y"].to_numpy() - fitted["yhat"].to_numpy()).std(ddof=1))
    last_date = pd.Timestamp(history["ds"].max())
    future_dates = pd.date_range(last_date + pd.offsets.MonthBegin(1), periods=6, freq="MS")
    future = model.predict(pd.DataFrame({"ds": future_dates}))
    return future[["ds", "yhat", "yhat_lower", "yhat_upper"]].reset_index(drop=True), residual_std


def forecast_all(db_path: Path = DUCKDB_PATH, proc_dir: Path = PROC_DIR) -> pd.DataFrame:
    """Forecast every current monthly indicator and record skipped series."""
    db_path, proc_dir = Path(db_path), Path(proc_dir)
    if not db_path.is_file():
        raise FileNotFoundError(f"[forecast] Missing {db_path}; run load_duckdb first")
    proc_dir.mkdir(parents=True, exist_ok=True)
    metrics = []
    for code in FORECAST_CODES:
        history = load_history(db_path, code)
        if not is_monthly(history):
            print(f"[forecast] WARNING {code}: no usable monthly history; skipping Prophet")
            (proc_dir / f"forecast_{code}.parquet").unlink(missing_ok=True)
            metrics.append({"indicator_code": code, "status": "skipped_non_monthly",
                            "residual_std": float("nan"), "observations": len(history),
                            "training_end": history["ds"].max() if not history.empty else pd.NaT})
            continue
        future, residual_std = forecast_one(history)
        out = proc_dir / f"forecast_{code}.parquet"
        future.to_parquet(out, index=False)
        metrics.append({"indicator_code": code, "status": "forecasted",
                        "residual_std": residual_std, "observations": len(history),
                        "training_end": history["ds"].max()})
        print(f"[forecast] {code}: residual std={residual_std:.3f}; next six months:\n"
              + future.to_string(index=False))
    result = pd.DataFrame(metrics)
    result.to_parquet(proc_dir / "forecast_metrics.parquet", index=False)
    print("[forecast] saved forecast_metrics.parquet")
    return result


def main() -> None:
    """Run the standalone Prophet forecasting stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DUCKDB_PATH)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    arguments = parser.parse_args()
    try:
        forecast_all(arguments.db_path, arguments.proc_dir)
    except RuntimeError as exc:
        print(exc)
        raise SystemExit(1) from exc
    except ImportError as exc:
        raise SystemExit("[forecast] Install Parquet support: python -m pip install pyarrow") from exc


if __name__ == "__main__":
    main()
