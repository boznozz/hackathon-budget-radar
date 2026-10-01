"""Build the requested time, indicator, budget, and illustrative shock tables."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
except ImportError as exc:
    raise SystemExit("[build_star] Install dependencies: python -m pip install -r requirements.txt") from exc

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.clean import PROC_DIR


INDICATORS = {
    "BRENT": ("brent", "Brent crude", "USD/bbl", "commodity"),
    "GOLD": ("gold", "Gold futures", "USD/oz", "commodity"),
    "EURTND": ("eur_tnd", "EUR/TND", "TND/EUR", "currency"),
    "USDTND": ("usd_tnd", "USD/TND", "TND/USD", "currency"),
    "WHEAT": ("wheat", "Chicago wheat", "USD/tonne", "commodity"),
    "CPI": ("wb_inflation", "Tunisia consumer inflation", "%", "macro"),
}
BUDGET_BASELINES = {
    "fuel_subsidies": 8000.0,
    "customs_revenue": 12000.0,
    "food_subsidies": 3000.0,
    "debt_service": 15000.0,
    "social_spending": 20000.0,
}
# CME quotes ZW wheat in cents/bushel; USDA reports 36.7437 bushels/tonne.
WHEAT_CENTS_PER_BUSHEL_TO_USD_PER_TONNE = 36.7437 / 100


def read_cleaned(proc_dir: Path, name: str) -> pd.DataFrame:
    """Return a cleaned source or an empty frame when that source is absent."""
    path = proc_dir / f"{name}.parquet"
    if not path.is_file():
        print(f"[build_star] WARNING missing {path.name}; skipping")
        return pd.DataFrame()
    return pd.read_parquet(path)


def build_indicators(proc_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Map raw close prices and observed CPI values to the six target codes."""
    rows: list[pd.DataFrame] = []
    dimensions = []
    for code, (source, name, unit, category) in INDICATORS.items():
        dimensions.append({"code": code, "name": name, "unit": unit, "category": category})
        frame = read_cleaned(proc_dir, source)
        if frame.empty:
            continue
        value_column = "value" if code == "CPI" else "close"
        if not {"date", value_column}.issubset(frame.columns):
            print(f"[build_star] WARNING {source} lacks date/{value_column}; skipping")
            continue
        values = frame[["date", value_column]].copy()
        values.columns = ["date", "value"]
        values["date"] = pd.to_datetime(values["date"], errors="coerce")
        values["value"] = pd.to_numeric(values["value"], errors="coerce")
        if code == "WHEAT":
            values["value"] *= WHEAT_CENTS_PER_BUSHEL_TO_USD_PER_TONNE
        values["indicator_code"] = code
        rows.append(values.dropna(subset=["date", "value"]))
    fact = (pd.concat(rows, ignore_index=True) if rows else
            pd.DataFrame(columns=["date", "value", "indicator_code"]))
    fact = fact[["date", "indicator_code", "value"]].drop_duplicates(
        ["date", "indicator_code"], keep="last").sort_values(
        ["indicator_code", "date"]).reset_index(drop=True)
    return pd.DataFrame(dimensions), fact


def synthetic_budget() -> pd.DataFrame:
    """Make deterministic monthly demo allocations because real monthly execution is absent.

    These are SYNTHETIC figures permitted for the hackathon demonstration.
    Annual baselines are illustrative, not observed monthly appropriations.
    """
    months = pd.date_range("2019-01-01", "2026-12-01", freq="MS")
    generator = np.random.default_rng(20260926)
    rows = []
    for budget_line, annual_baseline in BUDGET_BASELINES.items():
        for index, date in enumerate(months):
            trend = 1 + 0.0015 * index
            allocation = annual_baseline / 12 * trend * (1 + generator.normal(0, 0.01))
            execution = allocation * float(np.clip(0.91 + generator.normal(0, 0.025), 0, 1))
            rows.append({"date": date, "budget_line": budget_line,
                         "allocated_mtnd": round(allocation, 3),
                         "executed_mtnd": round(execution, 3),
                         "data_source": "SYNTHETIC"})
    return pd.DataFrame(rows)


def illustrative_shocks() -> pd.DataFrame:
    """Return named scenario labels; these are examples, not recorded events."""
    values = [
        ("HORMUZ", "Hormuz closure", "energy", "high", "2026-10-01", "2026-12-31"),
        ("EUR_SPIKE", "EUR/TND spike", "currency", "medium", "2026-10-01", "2026-12-31"),
        ("WHEAT", "Wheat crisis", "food", "high", "2026-10-01", "2026-12-31"),
        ("RED_SEA", "Red Sea disruption", "trade", "medium", "2026-10-01", "2026-12-31"),
    ]
    frame = pd.DataFrame(values, columns=["shock_id", "name", "type", "severity",
                                          "start_date", "end_date"])
    frame[["start_date", "end_date"]] = frame[["start_date", "end_date"]].apply(pd.to_datetime)
    return frame


def build_star(proc_dir: Path = PROC_DIR) -> dict[str, pd.DataFrame]:
    """Build and save all five star tables in the processed data lake."""
    proc_dir = Path(proc_dir)
    proc_dir.mkdir(parents=True, exist_ok=True)
    dimension, indicators = build_indicators(proc_dir)
    budget = synthetic_budget()
    dates = pd.Series(pd.concat([indicators["date"], budget["date"]],
                                ignore_index=True).dropna().unique())
    dates = pd.to_datetime(dates).sort_values().reset_index(drop=True)
    time = pd.DataFrame({"date": dates, "year": dates.dt.year,
                         "month": dates.dt.month, "quarter": dates.dt.quarter})
    tables = {"dim_time": time, "dim_indicator": dimension,
              "fact_indicators": indicators, "fact_budget": budget,
              "dim_shock": illustrative_shocks()}
    for name, frame in tables.items():
        frame.to_parquet(proc_dir / f"{name}.parquet", index=False)
        print(f"[build_star] saved {name}.parquet ({len(frame)} rows)")
    return tables


def main() -> None:
    """Run the standalone star-building stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    arguments = parser.parse_args()
    try:
        build_star(arguments.proc_dir)
    except ImportError as exc:
        raise SystemExit("[build_star] Install Parquet support: python -m pip install pyarrow") from exc


if __name__ == "__main__":
    main()
