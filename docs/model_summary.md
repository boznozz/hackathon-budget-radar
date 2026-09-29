# Model summary

The **raw layer** holds scraped CSV/JSON unchanged. The cleaning stage prints
source schemas, normalizes dates and column names, and writes per-source Parquet.
The **star layer** joins observed indicators with time and indicator dimensions.
`fact_budget` is a deterministic synthetic monthly demonstration for the five
target lines, from January 2019 through December 2026. Real monthly allocation
and execution for those exact lines was unavailable; every synthetic row has
`data_source = SYNTHETIC`.

**DuckDB** serves read-only analytical queries for Prophet, anomaly detection,
and the dashboard. Prophet fits monthly observations with yearly seasonality
and creates six monthly forecasts plus in-sample residual standard deviation.
The anomaly stage compares each observation with the previous 12 observations
and flags absolute z-scores above 2.5. CPI is observed only annually in the
available World Bank file; the INS export is marked synthetic. CPI is therefore
kept in the star table but not modeled as a monthly series.
For month `t`, the score is `(value_t - mean(previous 12 values)) /
sample_std(previous 12 values)`. The current month is excluded; a flat prior
window uses `1e-9` as its denominator. The dashboard hides the internal
`is_anomaly` flag and displays only flagged rows with their scores.

**Transmission and scenarios** use the exact elasticity matrix in the supplied
brief. Its coefficients and the five budget baselines are illustrative expert
assumptions, **not** estimates from historical correlation or causal inference.
Each line's relative impact is the sum of `elasticity × indicator shock`; MTND
impact is baseline times that sum. GOLD is forecast and selectable but has no
budget elasticity in the provided matrix. Named disruptions in `dim_shock` are
illustrative labels, not claims that those events occurred.

**GPO/OKR** maps absolute impacts below 2% to GREEN, below 10% to YELLOW, and
10% or more to RED. Its French objectives and SMART actions are draft proposals;
no ministry owner or policy decision is asserted. The dashboard shows the
source series, Prophet intervals, flagged points, scenario impacts, and GPO
response together.

**Limits and next steps:** replace synthetic budget rows and assumed elasticities
with validated ministry execution and expert calibration; acquire real monthly
CPI; backtest forecasts on held-out months; confirm that Yahoo futures quotes
match the fiscal exposure being modeled. Chicago wheat is quoted in cents per
bushel by [CME](https://www.cmegroup.com/education/brochures-and-handbooks/wheat-futures-and-options);
the conversion uses the [USDA factor of 36.7437 bushels per metric tonne](https://www-tx.ers.usda.gov/data-products/wheat-data/documentation).

**External news overlay:** NewsAPI searches recent international economic
headlines and descriptions; Gemini groups and screens concrete events against
the six-month Prophet horizon using structured JSON. Cited, medium/high
confidence signals become bounded, decaying scenario adjustments: commodity
shifts are capped at 15% and currency shifts at 6% across simultaneous events.
The orange dashboard curve is conditional and illustrative, not a refitted
forecast or a calibrated confidence interval. Source articles and assumed
impacts should be reviewed before policy use.
Early Warning lists only budget categories whose modeled impact changes with
the news scenario, showing before/after amounts and the contributing event
signals. Scenario Simulator applies user-selected shocks to each of the six
Prophet forecast months and displays those projected indicator values alongside
the elasticity-based budget effects.
