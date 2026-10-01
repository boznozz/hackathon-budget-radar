"""
Open Budget Tunisia -> T19 Data Lake
Python 3.11+

FINAL OUTPUT
------------
data/raw/openbudget.json

RAW DATA
--------
data/raw/openbudget_raw/

Strategy
--------
1. Open each dashboard separately for each year.
2. Pass ?year=YYYY where supported.
3. Capture XHR/fetch/JSON/CSV/XLSX responses.
4. Capture browser downloads.
5. Associate every capture with the dashboard AND year
   that generated it.
6. Parse only the dashboard relevant to the requested section.
7. Produce one deterministic JSON file.

No fabricated values.
Missing values remain null / empty.

Portal currently exposes:
2020-2026

2019 remains in the schema but is empty if unavailable.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://openbudget.finances.gov.tn"

RAW_DIR = Path("data/raw")
RAW_CAPTURE_DIR = RAW_DIR / "openbudget_raw"
OUTPUT_FILE = RAW_DIR / "openbudget.json"

RAW_DIR.mkdir(parents=True, exist_ok=True)
RAW_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

TARGET_YEARS = list(range(2019, 2027))
PORTAL_YEARS = list(range(2020, 2027))

REQUEST_DELAY = 0.8
REQUEST_TIMEOUT = 45
PAGE_TIMEOUT = 120_000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36 "
    "T19-OpenBudget-Research/3.0"
)


# ============================================================
# DASHBOARDS
# ============================================================

DASHBOARDS = {
    "global_trends": {
        "url": f"{BASE_URL}/fr/global-trends-new/",
        "section": "global_trends",
    },

    "budget_by_program": {
        "url": f"{BASE_URL}/fr/where-does-the-money-go-program/",
        "section": "budget_by_mission",
    },

    "budget_by_program_lf_cp": {
        "url": f"{BASE_URL}/fr/where-does-the-money-go-lf-program/",
        "section": "budget_by_mission",
    },

    "development_expenditures": {
        "url": f"{BASE_URL}/fr/development-related-expenditures/",
        "section": "budget_by_mission",
    },

    "ordinary_interventions": {
        "url": f"{BASE_URL}/fr/ordinary-intervention-expenditures/",
        "section": "economic_classification",
    },

    "compensation_expenditures": {
        "url": f"{BASE_URL}/fr/compensation-expenditures/",
        "section": "economic_classification",
    },

    "economic_execution": {
        "url": f"{BASE_URL}/fr/execution-by-economic-nature/",
        "section": "economic_classification",
    },
}


# ============================================================
# OPTIONAL VERIFIED ENDPOINTS
# ============================================================

KNOWN_ENDPOINTS: dict[str, list[str]] = {}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("openbudget")


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(value: Any) -> str:

    if value is None:
        return ""

    text = str(value).lower().strip()

    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "à": "a",
        "â": "a",
        "ä": "a",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ô": "o",
        "ö": "o",
        "î": "i",
        "ï": "i",
        "ç": "c",
        "œ": "oe",
        "’": "'",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def parse_number(value: Any) -> float | None:

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):

        if pd.isna(value):
            return None

        return float(value)

    text = str(value).strip()

    if not text:
        return None

    text = re.sub(
        r"[^\d,.\-]",
        "",
        text,
    )

    if not text:
        return None

    if "," in text and "." in text:

        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")

    elif "," in text:

        parts = text.split(",")

        if len(parts) == 2 and len(parts[1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")

    try:
        return float(text)

    except ValueError:
        return None


def clean_number(value: float | None):

    if value is None:
        return None

    if float(value).is_integer():
        return int(value)

    return round(float(value), 6)


# ============================================================
# FILE HELPERS
# ============================================================

def safe_filename(value: str) -> str:

    value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value,
    )

    return value[:180]


def save_raw(
    dashboard: str,
    year: int | None,
    url: str,
    content_type: str,
    body: bytes,
) -> Path:

    parsed = urlparse(url)

    year_text = (
        str(year)
        if year is not None
        else "unknown"
    )

    name = safe_filename(
        f"{dashboard}_{year_text}_"
        f"{parsed.netloc}_{parsed.path}"
    )

    content_type_lower = content_type.lower()
    url_lower = url.lower()

    if (
        "json" in content_type_lower
        or ".json" in url_lower
    ):
        extension = ".json"

    elif (
        "csv" in content_type_lower
        or ".csv" in url_lower
    ):
        extension = ".csv"

    elif (
        "spreadsheet" in content_type_lower
        or "excel" in content_type_lower
        or ".xlsx" in url_lower
    ):
        extension = ".xlsx"

    else:
        extension = ".bin"

    path = RAW_CAPTURE_DIR / (
        name + extension
    )

    counter = 1
    original = path

    while path.exists():

        path = (
            original.parent
            / f"{original.stem}_{counter}"
            f"{original.suffix}"
        )

        counter += 1

    path.write_bytes(body)

    return path


def write_json(
    path: Path,
    data: Any,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# HTTP
# ============================================================

def create_session():

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept": "*/*",
        }
    )

    return session


def request_with_retry(
    session,
    url: str,
    attempts: int = 3,
):

    for attempt in range(attempts):

        try:

            time.sleep(REQUEST_DELAY)

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            return response

        except requests.RequestException as exc:

            if attempt == attempts - 1:

                logger.warning(
                    "Request failed: %s",
                    exc,
                )

                return None

            time.sleep(
                2 ** attempt
            )

    return None


# ============================================================
# PARSE RESPONSE
# ============================================================

def parse_body(
    body: bytes,
    content_type: str,
    url: str,
):

    content_type = content_type.lower()
    url_lower = url.lower()

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    if (
        "json" in content_type
        or ".json" in url_lower
    ):

        try:

            return json.loads(
                body.decode(
                    "utf-8",
                    errors="replace",
                )
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    if (
        "csv" in content_type
        or ".csv" in url_lower
    ):

        try:

            text = body.decode(
                "utf-8-sig",
                errors="replace",
            )

            return list(
                csv.DictReader(
                    io.StringIO(text)
                )
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # XLSX
    # --------------------------------------------------------

    if (
        "spreadsheet" in content_type
        or "excel" in content_type
        or ".xlsx" in url_lower
    ):

        try:

            workbook = pd.ExcelFile(
                io.BytesIO(body)
            )

            result = {}

            for sheet in workbook.sheet_names:

                df = pd.read_excel(
                    workbook,
                    sheet_name=sheet,
                )

                df = df.where(
                    pd.notnull(df),
                    None,
                )

                result[sheet] = (
                    df.to_dict(
                        orient="records"
                    )
                )

            return result

        except Exception:
            pass

    # --------------------------------------------------------
    # Some APIs return JSON as text/plain
    # --------------------------------------------------------

    try:

        decoded = body.decode(
            "utf-8",
            errors="replace",
        ).strip()

        if (
            decoded.startswith("{")
            or decoded.startswith("[")
        ):

            return json.loads(
                decoded
            )

    except Exception:
        pass

    return None


# ============================================================
# EXTRACT TABLE ROWS
# ============================================================

def extract_rows(
    body: Any,
) -> list[dict[str, Any]]:

    if body is None:
        return []

    # JSON list.
    if isinstance(body, list):

        return [
            item
            for item in body
            if isinstance(item, dict)
        ]

    # JSON object.
    if isinstance(body, dict):

        preferred = [
            "data",
            "results",
            "records",
            "rows",
            "items",
            "result",
            "dataset",
        ]

        for key in preferred:

            value = body.get(key)

            if isinstance(value, list):

                rows = [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

                if rows:
                    return rows

        # XLSX sheets.
        rows = []

        for sheet_name, value in body.items():

            if not isinstance(value, list):
                continue

            for item in value:

                if isinstance(item, dict):

                    row = dict(item)

                    row["_sheet"] = (
                        sheet_name
                    )

                    rows.append(row)

        if rows:
            return rows

    return []


# ============================================================
# COLUMN HELPERS
# ============================================================

def find_column(
    columns: list[str],
    aliases: list[str],
):

    normalized = {
        normalize_text(column): column
        for column in columns
    }

    # Exact match.
    for alias in aliases:

        key = normalize_text(alias)

        if key in normalized:
            return normalized[key]

    # Partial match.
    for column in columns:

        column_normalized = (
            normalize_text(column)
        )

        for alias in aliases:

            alias_normalized = (
                normalize_text(alias)
            )

            if (
                alias_normalized
                and alias_normalized
                in column_normalized
            ):
                return column

    return None


def get_value(
    row: dict[str, Any],
    aliases: list[str],
):

    column = find_column(
        list(row.keys()),
        aliases,
    )

    if column is None:
        return None

    return row.get(column)


# ============================================================
# YEAR DETECTION
# ============================================================

def detect_year_from_row(
    row: dict[str, Any],
):

    aliases = [
        "year",
        "annee",
        "année",
        "exercice",
        "annee fiscale",
        "exercice fiscal",
    ]

    value = get_value(
        row,
        aliases,
    )

    if value is not None:

        try:

            year = int(
                float(str(value))
            )

            if year in TARGET_YEARS:
                return year

        except Exception:
            pass

    return None


# ============================================================
# DIRECT RESOURCE DISCOVERY
# ============================================================

def discover_resources(
    session,
    dashboard_name: str,
    url: str,
):

    response = request_with_retry(
        session,
        url,
    )

    if response is None:
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    resources = set()

    # HTML links.
    for tag in soup.find_all(
        ["a", "link", "script"]
    ):

        attribute = (
            "href"
            if tag.name != "script"
            else "src"
        )

        value = tag.get(attribute)

        if not value:
            continue

        absolute = urljoin(
            url,
            value,
        )

        lower = absolute.lower()

        if any(
            token in lower
            for token in (
                ".json",
                ".csv",
                ".xlsx",
                ".xls",
                "/api/",
                "download",
                "export",
            )
        ):

            resources.add(
                absolute
            )

    logger.info(
        "[%s] direct resources: %d",
        dashboard_name,
        len(resources),
    )

    return sorted(resources)


# ============================================================
# DIRECT DOWNLOAD
# ============================================================

def download_resource(
    session,
    dashboard_name: str,
    year: int | None,
    url: str,
):

    response = request_with_retry(
        session,
        url,
    )

    if response is None:
        return None

    content_type = response.headers.get(
        "content-type",
        "",
    )

    path = save_raw(
        dashboard_name,
        year,
        url,
        content_type,
        response.content,
    )

    body = parse_body(
        response.content,
        content_type,
        url,
    )

    return {
        "dashboard": dashboard_name,
        "year": year,
        "url": url,
        "content_type": content_type,
        "path": str(path),
        "body": body,
    }


# ============================================================
# PLAYWRIGHT
# ============================================================

async def scrape_dashboard_year(
    dashboard_name: str,
    dashboard_url: str,
    year: int,
):

    captures = []

    # --------------------------------------------------------
    # VERY IMPORTANT:
    #
    # Open a fresh page for EACH YEAR.
    #
    # This means we don't have to guess which XHR belongs
    # to which year.
    # --------------------------------------------------------

    separator = (
        "&"
        if "?" in dashboard_url
        else "?"
    )

    year_url = (
        f"{dashboard_url}"
        f"{separator}year={year}"
    )

    logger.info(
        "[%s] YEAR %s -> %s",
        dashboard_name,
        year,
        year_url,
    )

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True,
        )

        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={
                "width": 1600,
                "height": 1000,
            },
            locale="fr-FR",
            accept_downloads=True,
        )

        page = await context.new_page()

        # ----------------------------------------------------
        # Capture responses
        # ----------------------------------------------------

        async def handle_response(response):

            request = response.request

            resource_type = (
                request.resource_type
            )

            content_type = response.headers.get(
                "content-type",
                "",
            )

            url = response.url

            url_lower = url.lower()
            type_lower = content_type.lower()

            interesting = (
                resource_type in {
                    "xhr",
                    "fetch",
                }
                or "json" in type_lower
                or "csv" in type_lower
                or "excel" in type_lower
                or "spreadsheet" in type_lower
                or ".json" in url_lower
                or ".csv" in url_lower
                or ".xlsx" in url_lower
                or "/api/" in url_lower
                or "download" in url_lower
                or "export" in url_lower
            )

            if not interesting:
                return

            try:

                body = await response.body()

            except Exception:
                return

            path = save_raw(
                dashboard_name,
                year,
                url,
                content_type,
                body,
            )

            parsed = parse_body(
                body,
                content_type,
                url,
            )

            captures.append(
                {
                    "dashboard": dashboard_name,
                    "year": year,
                    "url": url,
                    "content_type": content_type,
                    "resource_type": resource_type,
                    "path": str(path),
                    "body": parsed,
                }
            )

            rows = extract_rows(
                parsed
            )

            if rows:
                logger.info(
                    "[%s][%s] captured %d rows",
                    dashboard_name,
                    year,
                    len(rows),
                )
            else:
                logger.info(
                    "[%s][%s] captured response: %s",
                    dashboard_name,
                    year,
                    url,
                )

        page.on(
            "response",
            handle_response,
        )

        # ----------------------------------------------------
        # Navigate
        # ----------------------------------------------------

        try:

            await page.goto(
                year_url,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT,
            )

        except Exception as exc:

            logger.warning(
                "[%s][%s] navigation warning: %s",
                dashboard_name,
                year,
                exc,
            )

        # Allow dashboard to initialize.
        await page.wait_for_timeout(
            10000
        )

        # ----------------------------------------------------
        # Scroll
        # ----------------------------------------------------

        for _ in range(5):

            await page.mouse.wheel(
                0,
                1500,
            )

            await page.wait_for_timeout(
                1500
            )

        # ----------------------------------------------------
        # Try download buttons
        # ----------------------------------------------------

        labels = [
            "JSON",
            "CSV",
            "XLSX",
            "Excel",
            "Télécharger",
            "Download",
        ]

        for label in labels:

            try:

                locator = page.get_by_text(
                    label,
                    exact=False,
                )

                count = await locator.count()

                for index in range(
                    min(count, 3)
                ):

                    try:

                        async with page.expect_download(
                            timeout=5000
                        ) as download_info:

                            await locator.nth(
                                index
                            ).click(
                                timeout=3000
                            )

                        download = (
                            await download_info.value
                        )

                        filename = safe_filename(
                            f"{dashboard_name}_"
                            f"{year}_"
                            f"{download.suggested_filename}"
                        )

                        destination = (
                            RAW_CAPTURE_DIR
                            / filename
                        )

                        await download.save_as(
                            destination
                        )

                        logger.info(
                            "[%s][%s] DOWNLOAD -> %s",
                            dashboard_name,
                            year,
                            destination,
                        )

                        # ------------------------------------------------
                        # IMPORTANT:
                        # Parse the downloaded file and add it to captures.
                        # ------------------------------------------------

                        try:

                            body = (
                                destination.read_bytes()
                            )

                            content_type = ""

                            parsed = parse_body(
                                body,
                                content_type,
                                str(destination),
                            )

                            captures.append(
                                {
                                    "dashboard": dashboard_name,
                                    "year": year,
                                    "url": str(
                                        destination
                                    ),
                                    "content_type": (
                                        content_type
                                    ),
                                    "resource_type": (
                                        "download"
                                    ),
                                    "path": str(
                                        destination
                                    ),
                                    "body": parsed,
                                }
                            )

                            rows = extract_rows(
                                parsed
                            )

                            logger.info(
                                "[%s][%s] downloaded rows: %d",
                                dashboard_name,
                                year,
                                len(rows),
                            )

                        except Exception as exc:

                            logger.warning(
                                "[%s][%s] could not parse download: %s",
                                dashboard_name,
                                year,
                                exc,
                            )

                    except Exception:
                        continue

            except Exception:
                continue

        await page.wait_for_timeout(
            5000
        )

        await browser.close()

    return captures


# ============================================================
# GLOBAL TRENDS
# ============================================================

REVENUE_ALIASES = [
    "total revenues",
    "total revenue",
    "revenues",
    "recettes",
    "recettes totales",
    "recettes de l'etat",
    "recettes de l'état",
    "realisation recettes",
    "réalisation recettes",
]

EXPENDITURE_ALIASES = [
    "total expenditures",
    "total expenditure",
    "expenditures",
    "depenses",
    "dépenses",
    "dépenses totales",
    "realisation depenses",
    "réalisation dépenses",
]

BALANCE_ALIASES = [
    "budget balance",
    "balance budgetaire",
    "balance budgétaire",
    "solde budgetaire",
    "solde budgétaire",
    "solde",
]

DEBT_ALIASES = [
    "debt burden",
    "public debt",
    "dette publique",
    "charge de la dette",
    "charge dette",
    "debt",
    "dette",
]


def extract_global_trends(
    captures,
):

    result = {
        str(year): {
            "revenues": None,
            "expenditures": None,
            "balance": None,
            "debt": None,
        }
        for year in TARGET_YEARS
    }

    for capture in captures:

        if capture["dashboard"] != (
            "global_trends"
        ):
            continue

        year = capture.get("year")

        if year not in TARGET_YEARS:
            continue

        rows = extract_rows(
            capture.get("body")
        )

        for row in rows:

            revenues = clean_number(
                parse_number(
                    get_value(
                        row,
                        REVENUE_ALIASES,
                    )
                )
            )

            expenditures = clean_number(
                parse_number(
                    get_value(
                        row,
                        EXPENDITURE_ALIASES,
                    )
                )
            )

            balance = clean_number(
                parse_number(
                    get_value(
                        row,
                        BALANCE_ALIASES,
                    )
                )
            )

            debt = clean_number(
                parse_number(
                    get_value(
                        row,
                        DEBT_ALIASES,
                    )
                )
            )

            candidate = {
                "revenues": revenues,
                "expenditures": expenditures,
                "balance": balance,
                "debt": debt,
            }

            if not any(
                value is not None
                for value in candidate.values()
            ):
                continue

            current = result[
                str(year)
            ]

            for field, value in candidate.items():

                if (
                    value is not None
                    and current[field] is None
                ):
                    current[field] = value

    return result


# ============================================================
# MISSION
# ============================================================

MISSION_ALIASES = [
    "mission",
    "missions",
    "libelle mission",
    "libellé mission",
    "nom mission",
    "mission name",
]

ALLOCATED_ALIASES = [
    "allocated",
    "allocation",
    "allocated amount",
    "credits",
    "crédits",
    "credits alloues",
    "crédits alloués",
    "budget",
    "prevision",
    "prévision",
    "dotation",
]

EXECUTED_ALIASES = [
    "executed",
    "execution",
    "executed amount",
    "credits executed",
    "crédits exécutés",
    "credits payes",
    "crédits payés",
    "realisation",
    "réalisation",
]


def extract_missions(
    captures,
):

    result = {
        str(year): {}
        for year in TARGET_YEARS
    }

    for capture in captures:

        dashboard = capture[
            "dashboard"
        ]

        dashboard_config = DASHBOARDS.get(
            dashboard
        )

        if not dashboard_config:
            continue

        if dashboard_config[
            "section"
        ] != "budget_by_mission":
            continue

        year = capture.get("year")

        if year not in TARGET_YEARS:
            continue

        rows = extract_rows(
            capture.get("body")
        )

        for row in rows:

            mission_value = get_value(
                row,
                MISSION_ALIASES,
            )

            if mission_value is None:
                continue

            mission = str(
                mission_value
            ).strip()

            if not mission:
                continue

            if normalize_text(
                mission
            ) in {
                "total",
                "totale",
                "total general",
                "ensemble",
            }:
                continue

            allocated = clean_number(
                parse_number(
                    get_value(
                        row,
                        ALLOCATED_ALIASES,
                    )
                )
            )

            executed = clean_number(
                parse_number(
                    get_value(
                        row,
                        EXECUTED_ALIASES,
                    )
                )
            )

            if (
                allocated is None
                and executed is None
            ):
                continue

            current = result[
                str(year)
            ].setdefault(
                mission,
                {
                    "allocated": None,
                    "executed": None,
                },
            )

            if (
                allocated is not None
                and current["allocated"] is None
            ):
                current["allocated"] = allocated

            if (
                executed is not None
                and current["executed"] is None
            ):
                current["executed"] = executed

    # Sort missions.
    for year in TARGET_YEARS:

        result[
            str(year)
        ] = dict(
            sorted(
                result[
                    str(year)
                ].items(),
                key=lambda item:
                    normalize_text(
                        item[0]
                    ),
            )
        )

    return result


# ============================================================
# ECONOMIC CLASSIFICATION
# ============================================================

ECONOMIC_CATEGORIES = {
    "Subventions": [
        "subventions",
        "subvention",
        "compensation",
        "compensations",
    ],

    "Transferts": [
        "transferts",
        "transfert",
    ],

    "Charges de la dette": [
        "charges de la dette",
        "charge de la dette",
        "service de la dette",
        "debt service",
    ],

    "Recettes fiscales": [
        "recettes fiscales",
        "recette fiscale",
        "tax revenues",
        "impots",
        "impôts",
    ],

    "Recettes douanières": [
        "recettes douanieres",
        "recettes douanières",
        "recette douaniere",
        "recette douanière",
        "customs revenues",
    ],
}


def extract_economic(
    captures,
):

    result = {
        str(year): {}
        for year in TARGET_YEARS
    }

    for capture in captures:

        dashboard = capture[
            "dashboard"
        ]

        config = DASHBOARDS.get(
            dashboard
        )

        if not config:
            continue

        if config[
            "section"
        ] != "economic_classification":
            continue

        year = capture.get("year")

        if year not in TARGET_YEARS:
            continue

        rows = extract_rows(
            capture.get("body")
        )

        for row in rows:

            for category, aliases in (
                ECONOMIC_CATEGORIES.items()
            ):

                # First: category as a column.
                value = get_value(
                    row,
                    aliases,
                )

                number = parse_number(
                    value
                )

                if number is None:
                    continue

                result[
                    str(year)
                ][category] = clean_number(
                    number
                )

    # Fixed ordering.
    for year in TARGET_YEARS:

        ordered = {}

        for category in (
            ECONOMIC_CATEGORIES
        ):

            if category in result[
                str(year)
            ]:

                ordered[category] = result[
                    str(year)
                ][category]

        result[
            str(year)
        ] = ordered

    return result


# ============================================================
# MONTHLY EXECUTION
# ============================================================

MONTH_ALIASES = {
    1: ["jan", "janvier", "january"],
    2: ["feb", "fev", "fevrier", "february"],
    3: ["mar", "mars", "march"],
    4: ["apr", "avr", "avril", "april"],
    5: ["may", "mai"],
    6: ["jun", "juin", "june"],
    7: ["jul", "juil", "juillet", "july"],
    8: ["aug", "aou", "aout", "august"],
    9: ["sep", "sept", "septembre", "september"],
    10: ["oct", "octobre", "october"],
    11: ["nov", "novembre", "november"],
    12: ["dec", "decembre", "december"],
}

MONTH_NAMES = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def detect_month(
    row: dict[str, Any],
):

    for key, value in row.items():

        normalized_key = normalize_text(
            key
        )

        text = normalize_text(
            value
        )

        if normalized_key in {
            "month",
            "mois",
        }:

            try:

                month = int(
                    float(str(value))
                )

                if 1 <= month <= 12:
                    return month

            except Exception:
                pass

        for month_number, aliases in (
            MONTH_ALIASES.items()
        ):

            for alias in aliases:

                if text == normalize_text(
                    alias
                ):

                    return month_number

    return None


def extract_monthly(
    captures,
):

    # Prefer 2025.
    available_years = []

    for capture in captures:

        if capture[
            "dashboard"
        ] != "global_trends":
            continue

        year = capture.get("year")

        if year in PORTAL_YEARS:
            available_years.append(
                year
            )

    if not available_years:
        return {}

    year = (
        2025
        if 2025 in available_years
        else max(available_years)
    )

    monthly = {}

    for capture in captures:

        if capture[
            "dashboard"
        ] != "global_trends":
            continue

        if capture.get("year") != year:
            continue

        rows = extract_rows(
            capture.get("body")
        )

        for row in rows:

            month = detect_month(
                row
            )

            if month is None:
                continue

            revenues = clean_number(
                parse_number(
                    get_value(
                        row,
                        REVENUE_ALIASES,
                    )
                )
            )

            expenditures = clean_number(
                parse_number(
                    get_value(
                        row,
                        EXPENDITURE_ALIASES,
                    )
                )
            )

            if (
                revenues is None
                and expenditures is None
            ):
                continue

            monthly[month] = {
                "revenues": revenues,
                "expenditures": expenditures,
            }

    if not monthly:
        return {}

    ordered = {}

    for month in range(1, 13):

        if month in monthly:

            ordered[
                MONTH_NAMES[month]
            ] = monthly[month]

    return {
        str(year): ordered
    }


# ============================================================
# FINAL OUTPUT
# ============================================================

def build_final_output(
    captures,
):

    global_trends = (
        extract_global_trends(
            captures
        )
    )

    missions = extract_missions(
        captures
    )

    economic = extract_economic(
        captures
    )

    monthly = extract_monthly(
        captures
    )

    covered = set()

    for year, values in (
        global_trends.items()
    ):

        if any(
            value is not None
            for value in values.values()
        ):
            covered.add(
                int(year)
            )

    for year, values in (
        missions.items()
    ):

        if values:
            covered.add(
                int(year)
            )

    for year, values in (
        economic.items()
    ):

        if values:
            covered.add(
                int(year)
            )

    for year in monthly:
        covered.add(
            int(year)
        )

    covered = sorted(
        covered
    )

    return {
        "metadata": {
            "source": "Open Budget Tunisia",
            "url": BASE_URL,
            "scraped_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "years_requested": TARGET_YEARS,
            "years_covered": covered,
            "missing_years": [
                year
                for year in TARGET_YEARS
                if year not in covered
            ],
            "currency": "MTND",
            "notes": [
                "Official Open Budget Tunisia data only.",
                "No fabricated values.",
                "Missing values remain null or empty.",
                "2019 remains in the schema when unavailable.",
                "Raw captures are stored in data/raw/openbudget_raw/.",
            ],
        },

        "global_trends": global_trends,

        "budget_by_mission": missions,

        "budget_by_economic_classification": economic,

        "monthly_execution": monthly,
    }


def load_saved_captures():

    captures = []
    dashboard_names = sorted(
        DASHBOARDS,
        key=len,
        reverse=True,
    )

    for path in sorted(
        RAW_CAPTURE_DIR.glob("*.json")
    ):

        dashboard = next(
            (
                name
                for name in dashboard_names
                if path.name.startswith(
                    f"{name}_"
                )
            ),
            None,
        )

        if dashboard is None:
            continue

        year_match = re.match(
            rf"{re.escape(dashboard)}_(\d{{4}}|unknown)_",
            path.name,
        )

        if not year_match:
            continue

        year_text = year_match.group(1)

        try:
            body = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            continue

        captures.append(
            {
                "dashboard": dashboard,
                "year": (
                    int(year_text)
                    if year_text.isdigit()
                    else None
                ),
                "path": str(path),
                "body": body,
            }
        )

    return captures


def api_records(capture):

    body = capture.get("body")

    if not isinstance(body, dict):
        return []

    records = body.get("data")

    if not isinstance(records, list):
        return []

    return [
        record
        for record in records
        if isinstance(record, dict)
    ]


def to_mtnd(value):

    number = parse_number(value)

    if number is None:
        return None

    return clean_number(number / 1_000_000)


def saved_global_trends(captures):

    result = {
        str(year): {
            "revenues": None,
            "expenditures": None,
            "balance": None,
            "debt": None,
        }
        for year in TARGET_YEARS
    }

    for year in PORTAL_YEARS:
        for capture in captures:

            if (
                capture["dashboard"] != "global_trends"
                or capture["year"] != year
                or not re.search(
                    r"__api_gviz_runTableConf(?:_\d+)?\.json$",
                    capture["path"],
                )
            ):
                continue

            records = api_records(capture)
            labels = [
                normalize_text(
                    record.get("name", {}).get("fr", "")
                )
                for record in records
            ]

            revenue_table = any(
                label in {
                    "recettes fiscales",
                    "recettes non fiscales",
                    "dons",
                }
                for label in labels
            )

            expenditure_table = any(
                label.startswith("depenses ")
                or label.startswith("charges de financement")
                for label in labels
            )

            if revenue_table and result[str(year)]["revenues"] is None:

                amounts = [
                    parse_number(
                        record.get("financial", {})
                        .get(str(year), {})
                        .get("v6")
                    )
                    for record in records
                ]

                if any(amount is not None for amount in amounts):
                    result[str(year)]["revenues"] = to_mtnd(
                        sum(amount for amount in amounts if amount is not None)
                    )

            if (
                expenditure_table
                and result[str(year)]["expenditures"] is None
            ):

                amounts = [
                    parse_number(
                        record.get("financial", {})
                        .get(str(year), {})
                        .get("v4")
                    )
                    for record in records
                ]

                if any(amount is not None for amount in amounts):
                    result[str(year)]["expenditures"] = to_mtnd(
                        sum(amount for amount in amounts if amount is not None)
                    )

        current = result[str(year)]

        if (
            current["revenues"] is not None
            and current["expenditures"] is not None
        ):
            current["balance"] = clean_number(
                current["revenues"]
                - current["expenditures"]
            )

    return result


def saved_missions(captures):

    result = {
        str(year): {}
        for year in TARGET_YEARS
    }

    for capture in captures:

        if (
            capture["dashboard"] != "budget_by_program_lf_cp"
            or capture["year"] not in PORTAL_YEARS
            or not re.search(
                r"__api_gviz_runTableConf\.json$",
                capture["path"],
            )
        ):
            continue

        year = capture["year"]
        year_data = str(year)

        for record in api_records(capture):

            names = record.get("name", {})
            mission = names.get("fr")
            financial = record.get("financial", {}).get(year_data, {})

            if not mission or not isinstance(financial, dict):
                continue

            if normalize_text(mission) in {
                "total",
                "totale",
                "total general",
                "ensemble",
            }:
                continue

            normalized_mission = normalize_text(mission)

            if normalized_mission.startswith(
                ("depenses ", "charges de financement", "service de la dette")
            ):
                continue

            allocated = to_mtnd(financial.get("v1"))
            executed = to_mtnd(financial.get("v3"))

            if allocated is None and executed is None:
                continue

            result[year_data][mission] = {
                "allocated": allocated,
                "executed": executed,
            }

    for year in TARGET_YEARS:

        key = str(year)
        result[key] = dict(
            sorted(
                result[key].items(),
                key=lambda item: normalize_text(item[0]),
            )
        )

    return result


def saved_economic_classification(captures):

    result = {
        str(year): {}
        for year in TARGET_YEARS
    }

    for capture in captures:

        if (
            capture["dashboard"] == "global_trends"
            and capture["year"] in PORTAL_YEARS
            and re.search(
                r"__api_gviz_runTableConf(?:_\d+)?\.json$",
                capture["path"],
            )
        ):

            year = capture["year"]

            for record in api_records(capture):

                if normalize_text(
                    record.get("name", {}).get("fr", "")
                ) != "recettes fiscales":
                    continue

                financial = record.get("financial", {}).get(str(year), {})
                amount = (
                    financial.get("v6")
                    if isinstance(financial, dict)
                    else None
                )

                value = to_mtnd(amount)

                if value is not None:
                    result[str(year)]["Recettes fiscales"] = value
                break

        if (
            capture["dashboard"] != "compensation_expenditures"
            or capture["year"] not in PORTAL_YEARS
            or not re.search(
                r"__api_gviz_runTableConf\.json$",
                capture["path"],
            )
        ):
            continue

        for year in PORTAL_YEARS:

            total = 0.0
            found = False

            for record in api_records(capture):

                name = normalize_text(
                    record.get("name", {}).get("fr", "")
                )

                if "subvention" not in name:
                    continue

                financial = record.get("financial", {}).get(str(year), {})
                amount = parse_number(
                    financial.get("v1")
                    if isinstance(financial, dict)
                    else None
                )

                if amount is not None:
                    total += amount
                    found = True

            if found:
                result[str(year)]["Subventions"] = to_mtnd(total)

    return result


def build_saved_output(captures):

    global_trends = saved_global_trends(captures)
    missions = saved_missions(captures)
    economic = saved_economic_classification(captures)

    covered = set()

    for year, values in global_trends.items():

        if any(value is not None for value in values.values()):
            covered.add(int(year))

    for year, values in missions.items():

        if values:
            covered.add(int(year))

    for year, values in economic.items():

        if values:
            covered.add(int(year))

    covered = sorted(covered)

    return {
        "metadata": {
            "source": "Open Budget Tunisia",
            "url": BASE_URL,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "years_requested": TARGET_YEARS,
            "years_covered": covered,
            "missing_years": [
                year
                for year in TARGET_YEARS
                if year not in covered
            ],
            "currency": "MTND",
            "notes": [
                "Official Open Budget Tunisia raw captures only.",
                "Values are normalized to million Tunisian dinars (MTND).",
                "Global trend revenues and expenditures use annual budget amounts.",
                "Budget balance is calculated as revenues minus expenditures.",
                "Uncaptured values remain null or empty; no values are fabricated.",
                "2019 is unavailable in the saved portal captures.",
                "Monthly execution and debt totals were not present in the saved captures.",
            ],
        },
        "global_trends": global_trends,
        "budget_by_mission": missions,
        "budget_by_economic_classification": economic,
        "monthly_execution": {},
    }


# ============================================================
# MAIN
# ============================================================

async def main_async():

    logger.info("=" * 75)
    logger.info(
        "OPEN BUDGET TUNISIA - T19 DATA LAKE"
    )
    logger.info("=" * 75)

    session = create_session()

    captures = []

    # --------------------------------------------------------
    # Direct resources
    # --------------------------------------------------------

    logger.info(
        "STEP 1/3 - Discovering direct resources..."
    )

    for dashboard_name, config in (
        DASHBOARDS.items()
    ):

        resources = discover_resources(
            session,
            dashboard_name,
            config["url"],
        )

        for url in resources:

            resource = download_resource(
                session,
                dashboard_name,
                None,
                url,
            )

            if resource:
                captures.append(
                    resource
                )

    # --------------------------------------------------------
    # Playwright year-by-year
    # --------------------------------------------------------

    logger.info(
        "STEP 2/3 - Scraping dashboards year-by-year..."
    )

    for dashboard_name, config in (
        DASHBOARDS.items()
    ):

        logger.info(
            "=============================================="
        )

        logger.info(
            "DASHBOARD: %s",
            dashboard_name,
        )

        for year in PORTAL_YEARS:

            try:

                year_captures = (
                    await scrape_dashboard_year(
                        dashboard_name,
                        config["url"],
                        year,
                    )
                )

                captures.extend(
                    year_captures
                )

            except Exception as exc:

                logger.exception(
                    "[%s][%s] failed: %s",
                    dashboard_name,
                    year,
                    exc,
                )

    # --------------------------------------------------------
    # Build final JSON
    # --------------------------------------------------------

    logger.info(
        "STEP 3/3 - Building final JSON..."
    )

    result = build_final_output(
        captures
    )

    write_json(
        OUTPUT_FILE,
        result,
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    logger.info("=" * 75)

    logger.info(
        "FINAL OUTPUT:"
    )

    logger.info(
        "%s",
        OUTPUT_FILE.resolve(),
    )

    logger.info(
        "CAPTURES: %d",
        len(captures),
    )

    logger.info(
        "YEARS COVERED: %s",
        result["metadata"][
            "years_covered"
        ],
    )

    logger.info(
        "MISSING YEARS: %s",
        result["metadata"][
            "missing_years"
        ],
    )

    logger.info(
        "GLOBAL DATA: %s",
        [
            year
            for year, values
            in result[
                "global_trends"
            ].items()
            if any(
                value is not None
                for value in values.values()
            )
        ],
    )

    logger.info(
        "MISSION DATA: %s",
        [
            year
            for year, values
            in result[
                "budget_by_mission"
            ].items()
            if values
        ],
    )

    logger.info(
        "ECONOMIC DATA: %s",
        [
            year
            for year, values
            in result[
                "budget_by_economic_classification"
            ].items()
            if values
        ],
    )

    logger.info(
        "MONTHLY DATA: %s",
        list(
            result[
                "monthly_execution"
            ].keys()
        ),
    )

    logger.info("=" * 75)


def main():

    if "--from-raw" in sys.argv:

        captures = load_saved_captures()
        result = build_saved_output(captures)

        write_json(
            OUTPUT_FILE,
            result,
        )

        logger.info(
            "Built %s from %d saved captures; years covered: %s",
            OUTPUT_FILE,
            len(captures),
            result["metadata"]["years_covered"],
        )

        return

    asyncio.run(main_async())


if __name__ == "__main__":
    main()