"""Inspect and clean every local raw CSV/JSON without changing the source files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("[clean] Install dependencies: python -m pip install -r requirements.txt") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROC_DIR = PROJECT_ROOT / "data" / "processed"
EXPECTED = ("brent.csv", "gold.csv", "eur_tnd.csv", "usd_tnd.csv", "wheat.csv",
            "wb_gdp_growth.csv", "wb_inflation.csv", "wb_debt_gdp.csv",
            "douane_revenue.csv")


def snake_case(value: str) -> str:
    """Return a stable lowercase column name for raw source headers."""
    text = re.sub(r"[^0-9a-zA-Z]+", "_", str(value).strip().lower())
    return text.strip("_") or "column"


def inspect_csv(path: Path) -> pd.DataFrame:
    """Read one raw CSV and print its original shape and inferred dtypes."""
    frame = pd.read_csv(path, encoding="utf-8-sig")
    print(f"[clean] {path.name}: {len(frame)} rows; columns={list(frame.columns)}")
    print(f"[clean] {path.name}: dtypes={frame.dtypes.astype(str).to_dict()}")
    return frame


def clean_csv(path: Path) -> pd.DataFrame:
    """Normalize columns and dates, then discard duplicate or value-free rows."""
    frame = inspect_csv(path)
    frame.columns = [snake_case(column) for column in frame.columns]
    if "date" in frame:
        text_dates = frame["date"].astype("string").str.strip()
        years = text_dates.str.fullmatch(r"\d{4}").fillna(False)
        text_dates = text_dates.where(~years, text_dates + "-01-01")
        frame["date"] = pd.to_datetime(text_dates, errors="coerce")
    elif "year" in frame:
        frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
        frame.insert(0, "date", pd.to_datetime(frame["year"].astype("string") + "-01-01",
                                               errors="coerce"))
    values = [column for column in frame if column not in {"date", "year"}]
    if values:
        frame = frame.dropna(subset=values, how="all")
    return frame.dropna(how="all").drop_duplicates().reset_index(drop=True)


def flatten_openbudget(payload: dict[str, Any]) -> pd.DataFrame:
    """Keep the observed annual budget fields as tidy rows in MTND."""
    rows: list[dict[str, Any]] = []
    for year, values in payload.get("global_trends", {}).items():
        for name, amount in values.items():
            if amount is not None:
                rows.append({"date": pd.Timestamp(f"{year}-01-01"), "category": "global",
                             "budget_line": name, "measure": "annual_budget",
                             "value_mtnd": float(amount)})
    for year, missions in payload.get("budget_by_mission", {}).items():
        for name, measures in missions.items():
            for measure, amount in measures.items():
                if amount is not None:
                    rows.append({"date": pd.Timestamp(f"{year}-01-01"), "category": "mission",
                                 "budget_line": name, "measure": measure,
                                 "value_mtnd": float(amount)})
    for year, values in payload.get("budget_by_economic_classification", {}).items():
        for name, amount in values.items():
            if amount is not None:
                rows.append({"date": pd.Timestamp(f"{year}-01-01"), "category": "economic",
                             "budget_line": name, "measure": "annual_budget",
                             "value_mtnd": float(amount)})
    return pd.DataFrame(rows, columns=["date", "category", "budget_line", "measure", "value_mtnd"])


def flatten_ins(payload: dict[str, Any]) -> pd.DataFrame:
    """Use measured INS observations only; synthetic fallback carries no facts."""
    columns = ["date", "category", "indicator", "value"]
    if str(payload.get("metadata", {}).get("method", "")).startswith("fallback: synthetic"):
        print("[clean] ins.json is a synthetic fallback; no observations loaded")
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for category, groups in payload.items():
        if category == "metadata" or not isinstance(groups, dict):
            continue
        for frequency, observations in groups.items():
            if not isinstance(observations, list):
                continue
            for observation in observations:
                raw_date = str(observation.get("date", ""))
                date = (pd.Period(raw_date, freq="Q").start_time if frequency == "quarterly"
                        else pd.to_datetime(raw_date, errors="coerce"))
                for indicator, value in observation.items():
                    if indicator != "date" and value is not None and pd.notna(date):
                        rows.append({"date": date, "category": category,
                                     "indicator": indicator, "value": float(value)})
    return pd.DataFrame(rows, columns=columns).drop_duplicates().reset_index(drop=True)


def clean_json(path: Path) -> pd.DataFrame:
    """Flatten a known export, or retain scalar JSON leaves for an unknown one."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(f"[clean] {path.name}: top-level keys={list(payload) if isinstance(payload, dict) else 'list'}")
    if isinstance(payload, dict) and "global_trends" in payload:
        return flatten_openbudget(payload)
    if isinstance(payload, dict) and "cpi" in payload and "metadata" in payload:
        return flatten_ins(payload)
    rows: list[dict[str, str]] = []

    def visit(value: Any, location: str) -> None:
        """Walk unknown JSON without dropping information or storing Python objects."""
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{location}.{key}" if location else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{location}[{index}]")
        elif value is not None:
            rows.append({"path": location, "value": str(value)})

    visit(payload, "")
    return pd.DataFrame(rows, columns=["path", "value"]).drop_duplicates().reset_index(drop=True)


def clean_all(raw_dir: Path = RAW_DIR, proc_dir: Path = PROC_DIR) -> pd.DataFrame:
    """Clean every available raw file into a same-named Parquet and summarize it."""
    raw_dir, proc_dir = Path(raw_dir), Path(proc_dir)
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"[clean] Raw directory does not exist: {raw_dir}")
    proc_dir.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED:
        if not (raw_dir / name).is_file():
            print(f"[clean] WARNING missing {name}; skipping")
    if not any(raw_dir.glob("openbudget*.json")):
        print("[clean] WARNING missing openbudget JSON; skipping")
    summary: list[dict[str, Any]] = []
    for path in sorted(raw_dir.iterdir()):
        if path.suffix.lower() not in {".csv", ".json"}:
            continue
        try:
            frame = clean_csv(path) if path.suffix.lower() == ".csv" else clean_json(path)
        except (ValueError, KeyError, pd.errors.ParserError) as exc:
            print(f"[clean] WARNING could not parse {path.name}: {exc}; skipping")
            continue
        frame.to_parquet(proc_dir / f"{path.stem}.parquet", index=False)
        dates = pd.to_datetime(frame["date"], errors="coerce") if "date" in frame else pd.Series(dtype="datetime64[ns]")
        summary.append({"file": path.name, "rows": len(frame),
                        "columns": ", ".join(frame.columns),
                        "date_min": dates.min(), "date_max": dates.max()})
        print(f"[clean] saved {path.stem}.parquet ({len(frame)} rows)")
    result = pd.DataFrame(summary, columns=["file", "rows", "columns", "date_min", "date_max"])
    print("[clean] Summary:\n" + result.to_string(index=False))
    return result


def main() -> None:
    """Run the standalone clean stage with optional path overrides."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--proc-dir", type=Path, default=PROC_DIR)
    arguments = parser.parse_args()
    try:
        clean_all(arguments.raw_dir, arguments.proc_dir)
    except ImportError as exc:
        raise SystemExit("[clean] Install Parquet support: python -m pip install pyarrow") from exc


if __name__ == "__main__":
    main()
