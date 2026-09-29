"""Offline checks for the NewsAPI/Gemini forecast overlay."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.models.news_impact import (
    adjust_forecasts, fetch_news, load_news_snapshot, run_news_impact,
    validate_events,
)


NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.ok = True
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class NewsClient:
    def __init__(self):
        self.calls = []

    def get(self, url, *, headers, params, timeout):
        self.calls.append((url, headers, params, timeout))
        return FakeResponse({"status": "ok", "articles": [{
            "title": "Oil port closure in Libya", "url": "https://example.org/oil?utm_source=x",
            "source": {"name": "Example Wire"}, "publishedAt": "2026-09-25T10:00:00Z",
            "description": "Oil exports halted at a major port.",
        }]})


class GeminiClient:
    def __init__(self, assessment):
        self.assessment = assessment
        self.request = None

    def post(self, url, *, headers, json, timeout):
        self.request = (url, headers, json, timeout)
        return FakeResponse({"candidates": [{"content": {"parts": [{
            "text": __import__("json").dumps(self.assessment),
        }]}}]})


def baseline(value=100.0):
    return pd.DataFrame({"ds": pd.date_range("2026-10-01", periods=6, freq="MS"),
                         "yhat": [value] * 6,
                         "yhat_lower": [value * .9] * 6,
                         "yhat_upper": [value * 1.1] * 6})


class NewsImpactTest(unittest.TestCase):
    def test_newsapi_deduplicates_and_sends_key_in_header(self):
        client = NewsClient()
        articles, errors = fetch_news("secret", now=NOW, client=client)
        self.assertFalse(errors)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["url"], "https://example.org/oil")
        self.assertEqual(client.calls[0][1], {"X-Api-Key": "secret"})
        self.assertNotIn("apiKey", client.calls[0][2])

    def test_model_output_must_have_supported_articles_and_months(self):
        articles = [{"id": "A001", "url": "https://example.org/oil",
                     "title": "Oil port closure in Libya", "description": "Libya exports halted"},
                    {"id": "A002", "url": "https://example.org/tunisia",
                     "title": "Tunisia fuel strike", "description": "Domestic strike in Tunis"}]
        signal = {"code": "BRENT", "direction": "up", "strength": "high",
                  "start_month": 1, "duration_months": 3, "reason": "Supply loss"}
        event = {"title": "Port closure", "summary": "Exports halted",
                 "event_scope": "external", "event_location": "Libya",
                 "confidence": "high", "article_ids": ["A001"], "signals": [signal]}
        output = {"events": [dict(event, article_ids=["invented"]),
                             dict(event, confidence="low"),
                             dict(event, event_scope="domestic"),
                             dict(event, article_ids=["A002"]),
                             dict(event, signals=[dict(signal, code="CPI")]),
                             event, event]}
        kept = validate_events(output, articles, {"BRENT": baseline()})
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["article_ids"], ["A001"])

    def test_run_writes_bounded_adjustment_and_detects_stale_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            proc_dir = Path(directory)
            baseline().to_parquet(proc_dir / "forecast_BRENT.parquet", index=False)
            event = {"title": "Oil port closure", "summary": "Exports halted in Libya",
                     "event_scope": "external", "event_location": "Libya",
                     "confidence": "high", "article_ids": ["A001"], "signals": [{
                         "code": "BRENT", "direction": "up", "strength": "high",
                         "start_month": 1, "duration_months": 3, "reason": "Supply loss",
                     }]}
            gemini = GeminiClient({"events": [event]})
            snapshot = run_news_impact(
                proc_dir, news_api_key="news-secret", gemini_api_key="gemini-secret",
                now=NOW, news_client=NewsClient(), gemini_client=gemini,
            )
            self.assertEqual(len(snapshot["events"]), 1)
            self.assertEqual(gemini.request[2]["generationConfig"]["responseFormat"]
                             ["text"]["schema"]["type"], "object")
            self.assertEqual(gemini.request[2]["generationConfig"]["responseFormat"]
                             ["text"]["mimeType"], "APPLICATION_JSON")
            adjusted = pd.read_parquet(proc_dir / "news_adjusted_BRENT.parquet")
            self.assertAlmostEqual(adjusted.iloc[0]["yhat"], 108.0)
            self.assertAlmostEqual(adjusted.iloc[1]["yhat"], 106.8)
            self.assertAlmostEqual(adjusted.iloc[3]["yhat"], 100.0)
            self.assertIsNotNone(load_news_snapshot(proc_dir))
            self.assertNotIn("gemini-secret", (proc_dir / "news_snapshot.json").read_text())
            baseline(101).to_parquet(proc_dir / "forecast_BRENT.parquet", index=False)
            self.assertIsNone(load_news_snapshot(proc_dir))

    def test_combined_shocks_are_capped(self):
        event = {"signals": [{"code": "BRENT", "direction": "up", "strength": "high",
                              "start_month": 1, "duration_months": 6}]}
        frame = adjust_forecasts({"BRENT": baseline()}, [event, event, event])["BRENT"]
        self.assertAlmostEqual(frame.iloc[0]["relative_adjustment"], .15)


if __name__ == "__main__":
    unittest.main()
