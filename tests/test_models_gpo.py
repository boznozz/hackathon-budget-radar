"""Check Prophet output, prior-window anomalies, transmission, and GPO rules."""

from __future__ import annotations

import unittest

import pandas as pd

from src.gpo.okr_engine import OBJECTIVES, evaluate, generate_smart_actions
from src.models.anomaly import rolling_anomalies
from src.models.forecast import forecast_one
from src.models.scenario import ELASTICITIES, simulate


class ModelGPOTest(unittest.TestCase):
    def test_scenario_and_risk_thresholds(self) -> None:
        """Use the supplied elasticities and preserve exact threshold edges."""
        self.assertEqual(ELASTICITIES["fuel_subsidies"]["BRENT"], 0.85)
        results = simulate({"BRENT": 0.30, "USDTND": 0.10},
                           {"fuel_subsidies": 8000, "customs_revenue": 12000})
        self.assertAlmostEqual(results["fuel_subsidies"]["impact_pct"], 0.295)
        self.assertAlmostEqual(results["fuel_subsidies"]["impact_mtnd"], 2360)
        self.assertEqual(evaluate("fuel_subsidies", 0.019)["status"], "GREEN")
        self.assertEqual(evaluate("fuel_subsidies", 0.02)["status"], "YELLOW")
        self.assertEqual(evaluate("fuel_subsidies", -0.10)["status"], "RED")
        self.assertEqual(len(OBJECTIVES), 5)
        action = generate_smart_actions("fuel_subsidies", 0.295, 2360)[0]
        self.assertEqual(set(action), {"action", "specific", "measurable", "achievable",
                                       "relevant", "time_bound"})
        self.assertIn("MTND", action["measurable"])

    def test_prophet_and_prior_window_anomaly(self) -> None:
        """Fit six future months and flag a spike against earlier months only."""
        dates = pd.date_range("2023-01-01", periods=30, freq="MS")
        history = pd.DataFrame({"ds": dates, "y": [80 + index * 0.5 for index in range(30)]})
        future, residual_std = forecast_one(history)
        self.assertEqual(len(future), 6)
        self.assertEqual(future.iloc[0]["ds"], pd.Timestamp("2025-07-01"))
        self.assertTrue(set(["ds", "yhat", "yhat_lower", "yhat_upper"]).issubset(future))
        self.assertGreaterEqual(residual_std, 0)
        samples = pd.DataFrame({"date": dates, "indicator_code": "BRENT",
                                "value": [80.0] * 29 + [160.0]})
        result = rolling_anomalies(samples)
        self.assertTrue(bool(result.iloc[-1]["is_anomaly"]))
        self.assertEqual(int(result["is_anomaly"].sum()), 1)


if __name__ == "__main__":
    unittest.main()
