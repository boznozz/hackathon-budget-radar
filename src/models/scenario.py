"""Translate relative indicator shocks into illustrative budget-line impacts."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("[scenario] Install dependencies: python -m pip install -r requirements.txt") from exc

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.build_star import BUDGET_BASELINES
from src.etl.clean import PROC_DIR
from src.etl.load_duckdb import DUCKDB_PATH


# Illustrative expert assumptions from the supplied hackathon brief, not fitted coefficients.
ELASTICITIES: dict[str, dict[str, float]] = {
    "fuel_subsidies": {"BRENT": 0.85, "USDTND": 0.40},
    "customs_revenue": {"USDTND": -0.30, "CPI": 0.60},
    "food_subsidies": {"WHEAT": 0.70, "USDTND": 0.35},
    "debt_service": {"EURTND": 0.25, "USDTND": 0.25},
    "social_spending": {"CPI": 0.50},
}


def simulate(shocks: dict[str, float], baseline: dict[str, float]) -> dict[str, dict[str, float]]:
    """Compute additive elasticities for every budget line in million TND."""
    unknown = set(shocks) - {code for rates in ELASTICITIES.values() for code in rates} - {"GOLD"}
    if unknown:
        raise ValueError(f"Unknown shock codes: {', '.join(sorted(unknown))}")
    result: dict[str, dict[str, float]] = {}
    for budget_line, base in baseline.items():
        if budget_line not in ELASTICITIES:
            raise ValueError(f"Unknown budget line: {budget_line}")
        if not math.isfinite(float(base)) or float(base) < 0:
            raise ValueError(f"Invalid baseline for {budget_line}")
        impact_pct = 0.0
        for code, elasticity in ELASTICITIES[budget_line].items():
            shock = float(shocks.get(code, 0.0))
            if not math.isfinite(shock) or shock < -1 or shock > 10:
                raise ValueError(f"Invalid relative shock for {code}")
            impact_pct += elasticity * shock
        result[budget_line] = {"baseline": float(base), "impact_pct": impact_pct,
                               "impact_mtnd": float(base) * impact_pct}
    return result


def shocks_from_forecasts(proc_dir: Path = PROC_DIR,
                          db_path: Path = DUCKDB_PATH) -> dict[str, float]:
    """Compare six-month Prophet means with the last observed indicator values."""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("[scenario] Install DuckDB: python -m pip install duckdb") from exc
    with duckdb.connect(str(db_path), read_only=True) as connection:
        latest = connection.execute("""
            SELECT indicator_code, value FROM (
                SELECT indicator_code, value,
                       row_number() OVER (PARTITION BY indicator_code ORDER BY date DESC) AS rank
                FROM fact_indicators
            ) WHERE rank = 1
        """).df().set_index("indicator_code")["value"].to_dict()
    shocks: dict[str, float] = {}
    for code, previous in latest.items():
        path = Path(proc_dir) / f"forecast_{code}.parquet"
        if not path.is_file() or not previous:
            print(f"[scenario] WARNING {code}: forecast unavailable; skipping")
            continue
        future = pd.read_parquet(path)
        if future.empty:
            continue
        shocks[code] = float(future["yhat"].mean() / previous - 1)
    return shocks


def main() -> None:
    """Print the default scenario implied by available Prophet forecasts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    parser.add_argument("--db-path", type=Path, default=DUCKDB_PATH)
    arguments = parser.parse_args()
    try:
        shocks = shocks_from_forecasts(arguments.proc_dir, arguments.db_path)
    except RuntimeError as exc:
        print(exc)
        raise SystemExit(1) from exc
    except ImportError as exc:
        raise SystemExit("[scenario] Install Parquet support: python -m pip install pyarrow") from exc
    impacts = simulate(shocks, BUDGET_BASELINES)
    print(f"[scenario] forecast-derived relative shocks: {shocks}")
    print("[scenario] impacts (illustrative MTND):\n"
          + pd.DataFrame.from_dict(impacts, orient="index").to_string())


if __name__ == "__main__":
    main()
