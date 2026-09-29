"""
Scrape international indicators: Brent, Gold, EUR/TND, USD/TND via Yahoo Finance,
plus World Bank macro indicators for Tunisia.
All free, no API key required.
"""
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def fetch_world_bank(indicator: str, name: str):
    """Download a World Bank indicator for Tunisia and save as CSV."""
    print(f"[worldbank] fetching {name} ({indicator})...")
    url = (
        f"https://api.worldbank.org/v2/country/TN/indicator/{indicator}"
        f"?format=json&per_page=200"
    )
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"[worldbank] ERROR: {e}")
        return None

    if len(payload) < 2 or not payload[1]:
        print(f"[worldbank] no data for {indicator}")
        return None

    rows = [
        {"date": item["date"], "value": item["value"]}
        for item in payload[1]
        if item.get("value") is not None
    ]
    df = pd.DataFrame(rows)
    out = RAW_DIR / f"wb_{name}.csv"
    df.to_csv(out, index=False)
    print(f"[worldbank] saved {out} ({len(df)} rows)")
    return df

def fetch_yahoo(ticker: str, name: str, period: str = "5y", interval: str = "1mo"):
    """Download a Yahoo Finance series and save as CSV."""
    print(f"[yahoo] fetching {name} ({ticker})...")
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        print(f"[yahoo] WARNING: no data for {ticker}")
        return None
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    out = RAW_DIR / f"{name}.csv"
    df.to_csv(out, index=False)
    print(f"[yahoo] saved {out} ({len(df)} rows)")
    return df



def main():
    # --- Commodities & currencies via Yahoo Finance ---
    yahoo_targets = {
        "brent":    "BZ=F",        # Brent crude futures
        "gold":     "GC=F",        # Gold futures
        "eur_tnd":  "EURTND=X",    # EUR / TND
        "usd_tnd":  "USDTND=X",    # USD / TND
        "wheat":    "ZW=F",        # Wheat futures
    }
    for name, ticker in yahoo_targets.items():
        try:
            fetch_yahoo(ticker, name)
        except Exception as e:
            print(f"[yahoo] FAILED {name}: {e}")

    # --- World Bank macro indicators for Tunisia ---
    wb_targets = {
        "gdp_growth": "NY.GDP.MKTP.KD.ZG",   # GDP growth (annual %)
        "inflation":  "FP.CPI.TOTL.ZG",      # Inflation, consumer prices (annual %)
        "debt_gdp":   "GC.DOD.TOTL.GD.ZS",   # Central govt debt, total (% of GDP)
    }
    for name, code in wb_targets.items():
        try:
            fetch_world_bank(code, name)
        except Exception as e:
            print(f"[worldbank] FAILED {name}: {e}")

    print("\n[done] international data fetch complete.")


if __name__ == "__main__":
    main()