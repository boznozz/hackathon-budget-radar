"""Check the dashboard's news attribution and conditional projections."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app import (affected_budget_categories, agriculture_assessment, agriculture_chart,
                 category_impact_explanation,
                 driver_impact_explanation, news_event_shocks, scenario_forecasts)
from src.models.scenario import simulate
from src.utils.config import BASELINE_VALUES


class DashboardScenarioTest(unittest.TestCase):
    def test_only_news_affected_budget_category_is_reported(self) -> None:
        before = simulate({}, BASELINE_VALUES)
        after = simulate({"BRENT": .08}, BASELINE_VALUES)
        snapshot = {"events": [{"title": "External oil disruption", "signals": [{
            "code": "BRENT", "direction": "up", "strength": "high",
        }]}]}
        categories = affected_budget_categories(before, after, snapshot)
        self.assertEqual([item["line"] for item in categories], ["fuel_subsidies"])
        self.assertAlmostEqual(categories[0]["difference_pct_points"], 6.8)
        self.assertAlmostEqual(categories[0]["difference_mtnd"],
                               BASELINE_VALUES["fuel_subsidies"] * .068)

    def test_scenario_projects_all_six_forecast_months(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            dates = pd.date_range("2026-10-01", periods=6, freq="MS")
            pd.DataFrame({"ds": dates, "yhat": [100.0] * 6}).to_parquet(
                path / "forecast_BRENT.parquet", index=False)
            output = scenario_forecasts({"BRENT": .30}, path)
            self.assertEqual(len(output), 6)
            self.assertTrue((output["yhat"] == 100).all())
            self.assertTrue((output["scenario_yhat"] == 130).all())
            self.assertTrue((output["change_pct"] == 30).all())

    def test_fuel_news_explains_savings_erosion_in_tunisia(self) -> None:
        before = simulate({"BRENT": -.30}, BASELINE_VALUES)
        after = simulate({"BRENT": -.20}, BASELINE_VALUES)
        snapshot = {"events": [{"title": "Regional oil disruption", "signals": [{
            "code": "BRENT", "direction": "up", "strength": "high",
            "start_month": 1, "duration_months": 3,
        }]}]}
        category = affected_budget_categories(before, after, snapshot)[0]
        budget_text = category_impact_explanation(category)
        driver_text = driver_impact_explanation(category["line"], category["drivers"][0])
        self.assertIn("Dépense estimée", budget_text)
        self.assertIn("L'économie attendue se réduit", budget_text)
        self.assertIn("carburants en Tunisie", driver_text)
        self.assertIn("Élasticité supposée : +0,85", driver_text)
        self.assertIn("pendant 3 mois", driver_text)

    def test_agriculture_explains_event_without_inventing_a_budget_amount(self) -> None:
        results = agriculture_assessment({"BRENT": .08, "GOLD": .20})
        self.assertEqual([item["code"] for item in results], ["BRENT"])
        self.assertIn("carburant agricole", results[0]["impact"])
        self.assertIn("appui ciblé", results[0]["actions"][1])
        self.assertNotIn("MTND", str(results))

    def test_agriculture_graph_shows_indicator_changes_without_budget_amount(self) -> None:
        assessment = agriculture_assessment({"BRENT": .30, "USDTND": .10})
        chart = agriculture_chart(assessment)
        self.assertEqual(len(chart.data), 1)
        self.assertEqual(list(chart.data[0].x), [30.0, 10.0])
        self.assertEqual(list(chart.data[0].y), ["Pétrole Brent", "Dollar / dinar"])
        self.assertIn("achats agricoles", assessment[1]["actions"][0])
        self.assertNotIn("MTND", chart.layout.xaxis.title.text)

    def test_news_event_preset_respects_timing_across_six_months(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            dates = pd.date_range("2026-10-01", periods=6, freq="MS")
            pd.DataFrame({"ds": dates, "yhat": [100.0] * 6}).to_parquet(
                path / "forecast_BRENT.parquet", index=False)
            event = {"signals": [{"code": "BRENT", "direction": "up", "strength": "high",
                                  "start_month": 2, "duration_months": 3}]}
            shocks = news_event_shocks(event, path)
            self.assertAlmostEqual(shocks["BRENT"], .034)
            output = scenario_forecasts(shocks, path, event=event, event_defaults=shocks)
            self.assertEqual(output["scenario_yhat"].round(1).tolist(),
                             [100.0, 108.0, 106.8, 105.6, 100.0, 100.0])
            cleared = scenario_forecasts({"BRENT": 0.0}, path, event=event,
                                         event_defaults=shocks)
            self.assertTrue((cleared["scenario_yhat"] == 100).all())


if __name__ == "__main__":
    unittest.main()
