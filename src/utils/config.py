"""Central paths, indicators, baselines, and illustrative elasticity settings."""

from __future__ import annotations

from pathlib import Path

if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etl.build_star import BUDGET_BASELINES, INDICATORS
from src.etl.clean import PROC_DIR, PROJECT_ROOT, RAW_DIR
from src.etl.load_duckdb import DUCKDB_PATH
from src.models.scenario import ELASTICITIES


INDICATOR_CODES: tuple[str, ...] = tuple(INDICATORS)
BUDGET_LINES: tuple[str, ...] = tuple(BUDGET_BASELINES)
BASELINE_VALUES: dict[str, float] = BUDGET_BASELINES.copy()


def main() -> None:
    """Print the resolved configuration for a standalone sanity check."""
    print(f"[config] RAW_DIR={RAW_DIR}")
    print(f"[config] PROC_DIR={PROC_DIR}")
    print(f"[config] DUCKDB_PATH={DUCKDB_PATH}")
    print(f"[config] indicators={INDICATOR_CODES}")
    print(f"[config] budget_lines={BUDGET_LINES}")
    print(f"[config] baselines={BASELINE_VALUES}")
    print(f"[config] elasticities={ELASTICITIES}")


if __name__ == "__main__":
    main()
