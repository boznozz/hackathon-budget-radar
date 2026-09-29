"""Save an illustrative GPO review from the latest Prophet-derived shocks."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("[gpo.run] Install dependencies: python -m pip install -r requirements.txt") from exc

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.gpo.okr_engine import OBJECTIVES, evaluate, generate_smart_actions
from src.models.scenario import shocks_from_forecasts, simulate
from src.utils.config import BASELINE_VALUES, DUCKDB_PATH, PROC_DIR


def run_gpo(proc_dir: Path = PROC_DIR, db_path: Path = DUCKDB_PATH) -> dict[str, pd.DataFrame]:
    """Write risk assessments and French SMART actions as reviewable CSVs."""
    impacts = simulate(shocks_from_forecasts(proc_dir, db_path), BASELINE_VALUES)
    statuses = []
    actions = []
    for line, values in impacts.items():
        assessment = evaluate(line, values["impact_pct"])
        statuses.append({"budget_line": line, **values, **assessment,
                         "objective": OBJECTIVES[line]["objective"]})
        for action in generate_smart_actions(line, values["impact_pct"], values["impact_mtnd"]):
            actions.append({"budget_line": line, **action})
    tables = {"gpo_status": pd.DataFrame(statuses), "gpo_actions": pd.DataFrame(actions)}
    for name, frame in tables.items():
        frame.to_csv(Path(proc_dir) / f"{name}.csv", index=False, encoding="utf-8-sig")
        print(f"[gpo.run] saved {name}.csv ({len(frame)} rows)")
    return tables


def main() -> None:
    """Run standalone GPO export from available Prophet forecasts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    parser.add_argument("--db-path", type=Path, default=DUCKDB_PATH)
    arguments = parser.parse_args()
    run_gpo(arguments.proc_dir, arguments.db_path)


if __name__ == "__main__":
    main()
