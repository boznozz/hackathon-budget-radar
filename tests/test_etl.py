"""Verify raw cleaning, requested star tables, and DuckDB loading."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from src.etl.build_star import build_star
from src.etl.clean import clean_all
from src.etl.load_duckdb import load_duckdb


class ETLTest(unittest.TestCase):
    def test_local_sources_to_star_and_duckdb(self) -> None:
        """Keep raw bytes unchanged and handle sparse, partially missing inputs."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "raw"
            raw.mkdir()
            proc = root / "processed"
            database = root / "budget.duckdb"
            wheat = raw / "wheat.csv"
            wheat.write_text("date,close\n2025-01-01,100\n", encoding="utf-8")
            (raw / "douane_revenue.csv").write_text(
                "year,revenue_mtnd,contribution_pct\n2023,1849.0,\n2024,,\n",
                encoding="utf-8",
            )
            (raw / "ins.json").write_text(json.dumps({
                "metadata": {"method": "fallback: synthetic"},
                "cpi": {"monthly": [{"date": "2025-01", "value": 100}]},
            }), encoding="utf-8")
            original = wheat.read_bytes()
            summary = clean_all(raw, proc)
            self.assertEqual(wheat.read_bytes(), original)
            self.assertEqual(len(summary), 3)
            revenue = pd.read_parquet(proc / "douane_revenue.parquet")
            self.assertEqual(len(revenue), 1)
            self.assertEqual(revenue.iloc[0]["date"], pd.Timestamp("2023-01-01"))
            self.assertTrue(pd.read_parquet(proc / "ins.parquet").empty)

            tables = build_star(proc)
            self.assertEqual(len(tables["fact_budget"]), 480)
            self.assertEqual(set(tables["fact_budget"]["data_source"]), {"SYNTHETIC"})
            self.assertAlmostEqual(tables["fact_indicators"].iloc[0]["value"], 36.7437)
            self.assertEqual(len(tables["dim_shock"]), 4)
            counts = load_duckdb(proc, database, raw)
            self.assertEqual(counts["fact_budget"], 480)
            with duckdb.connect(str(database), read_only=True) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM fact_indicators").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
