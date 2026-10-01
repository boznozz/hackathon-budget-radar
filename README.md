# AI Budget Shock Radar & GPO Cockpit

Hackathon T19: a local demonstration of how external price and currency shocks
could affect five Tunisian budget lines. The ETL reads only `data/raw/` and
does not alter the scraped files. An optional news stage uses NewsAPI and
Gemini to create an event-adjusted forecast scenario.

## Setup

Use Python 3.11 or newer from the project directory:

```powershell
python -m pip install -r requirements.txt
```

## Run order

```powershell
python src/etl/clean.py
python src/etl/build_star.py
python src/etl/load_duckdb.py
python src/models/forecast.py
python src/models/anomaly.py
python src/models/scenario.py
python src/gpo/run.py
python src/models/news_impact.py  # optional; requires API keys
streamlit run app.py
```

`clean.py` prints every CSV schema and writes one cleaned Parquet per raw CSV/JSON.
`build_star.py` writes `dim_time`, `dim_indicator`, `fact_indicators`,
`fact_budget`, and `dim_shock` Parquet files. `load_duckdb.py` loads these and
the cleaned raw files into `data/budget.duckdb` and prints row/date checks.
Model files stay in Parquet, outside DuckDB. The two model stages write
`forecast_<CODE>.parquet`, `forecast_metrics.parquet`, and `anomalies.parquet`.
The GPO export writes `gpo_status.csv` and `gpo_actions.csv` for review.
The news stage writes `news_articles.json`, `news_snapshot.json`, and
`news_adjusted_<CODE>.parquet` under `data/processed/`.
Older `data/processed/star/`, `models/`, and `gpo/` folders from the previous
prototype may still be present locally; this pipeline ignores them.

The Streamlit interface has three French-language pages in a dark theme.
"Alertes et prévisions" compares Prophet with the news scenario, shows anomalies,
and explains the affected Tunisian budget categories. The sidebar scenario menu
contains the illustrative reference cases and each retained news event. Selecting
one opens "Simulation budgétaire" with five read-only indicator changes.
A news event keeps
its monthly timing in the chart, while the displayed values summarize its six-month
mean effect. "Pilotage par objectifs" uses the selected scenario and includes a
qualitative Agriculture panel with possible impacts and decisions. No agriculture
budget amount is calculated because the prototype has no dedicated baseline or
elasticity for that sector.

## NewsAPI and Gemini

Copy `.env.example` to `.env` and fill in `NEWSAPI_KEY` and `GEMINI_API_KEY`,
or set both as environment variables. Run `python src/models/news_impact.py`
after `forecast.py`, or click **Actualiser les actualités** in the Streamlit
sidebar. With keys configured, the Early Warning page also runs the news stage
once when there is no saved snapshot or the saved check is over 24 hours old;
ordinary reruns reuse the saved result. API failures appear on the page, and
editing `.env` is picked up on the next refresh.

NewsAPI searches recent coverage involving North Africa, Europe, oil, wheat,
shipping, and currency policy. Gemini sees the saved six-month Prophet
predictions and article headlines/descriptions, groups concrete events, and
returns cited directional signals. Fixed, capped percentages then create an
**illustrative after-news scenario**. The dashboard shows both curves, source
links, budget impact differences, and a warning banner for major signals.
These shifts are assumptions, not a refitted model or measured causal effect.
The app ignores a saved news scenario when its underlying Prophet forecasts
change. CPI is excluded because a monthly CPI forecast is unavailable.

NewsAPI's [Everything endpoint](https://newsapi.org/docs/endpoints/everything)
uses query terms rather than an article-origin country filter. Its
[developer plan](https://newsapi.org/pricing) has delayed articles and is for
development/testing; prompt breaking-news alerts require a suitable plan.

The five budget baselines and all elasticities are **illustrative assumptions**
from the supplied brief. Monthly execution for these exact budget lines was not
available, so `fact_budget` contains deterministic **SYNTHETIC** rows marked as
such. The INS export also identifies itself as synthetic and provides no real
monthly CPI observations. World Bank inflation is annual; CPI remains in the
indicator table but is skipped by the monthly Prophet forecast and anomaly
stage. Wheat futures quotes are converted from cents/bushel to USD/tonne.
Read [the model summary](docs/model_summary.md) before interpreting impacts.
