# AI Budget Shock Radar & GPO Cockpit

**Hackathon National « IA & Finances Publiques » — 25 & 26 septembre 2026**
**Défi T19 — Data Lake et prévisions budgétaires**

## Problem
The Tunisian state is good at reading past data but lacks forward-looking
planning tools. Budget is the citizen's money, and GPO (Gestion Par Objectif)
requires SMART objectives and KPIs.

## Solution
An AI-powered early-warning system that:
- Detects external shocks (oil, currency, wheat, gold, geopolitical risk)
- Forecasts their impact on budget lines
- Simulates scenarios (e.g., Hormuz closure, EUR/TND spike)
- Generates SMART actions aligned with GPO/OKR

## Architecture
Data lake (raw → processed Parquet) → DuckDB (OLAP) → Forecasting (Prophet)
→ Scenario Simulator → GPO/OKR Engine → Streamlit Dashboard

## Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium