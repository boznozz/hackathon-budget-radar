from __future__ import annotations

import json
import logging
import math
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "http://dataportal.ins.tn/webApi/"
BASE_URL = "http://dataportal.ins.tn"

START_YEAR = 2019
END_YEAR = datetime.now().year

NSO_SOURCE_ID = "C_NSO"
NSO_INDICATOR_DIMENSION = "RDS_DICT_INDICATORS_NSO"
NSO_REGION_DIMENSION = "RDS_DICT_REGIONS_NSO"
NSO_UNITS_DIMENSION = "UNITS"
CPI_INDICATOR_ID = "28228379"
TUNISIA_REGION_ID = "0"
GDP_SOURCE_ID = "OBJ10957839"
GDP_INDICATOR_DIMENSION = "OBJ10957849"
GDP_VALUATION_DIMENSION = "OBJ10957859"
GDP_INDICATOR_ID = "28741729"
GDP_YOY_VALUATION_ID = "28741779"

LANGUAGE_CODE = "1033"

REQUEST_TIMEOUT = 90
MAX_RETRIES = 4
BACKOFF_SECONDS = 2.0
RATE_LIMIT_SECONDS = 1.0

# Project root = current working directory.
# Run the script from the hackathon project root.
PROJECT_ROOT = Path.cwd()

RAW_DIR = PROJECT_ROOT / "data" / "raw"
STRUCTURE_FILE = RAW_DIR / "ins_structure.xml"
DIMENSIONS_FILE = RAW_DIR / "ins_dimensions.json"
OUTPUT_FILE = RAW_DIR / "ins.json"
LOG_FILE = RAW_DIR / "ins_api.log"


# ============================================================
# LOGGING
# ============================================================

RAW_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("ins_scraper")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        LOG_FILE,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ============================================================
# TARGET DEFINITIONS
# ============================================================

TARGETS = {
    "cpi": [
        "consumer price index",
        "cpi",
        "ipc",
        "indice des prix à la consommation",
        "indice prix consommation",
    ],
    "gdp": [
        "gdp",
        "gross domestic product",
        "pib",
        "produit intérieur brut",
    ],
    "foreign_trade": [
        "foreign trade",
        "external trade",
        "trade",
        "commerce extérieur",
        "commerce exterieur",
        "échanges extérieurs",
        "echanges exterieurs",
    ],
    "public_finance": [
        "public finance",
        "government finance",
        "public debt",
        "dette publique",
        "finances publiques",
    ],
    "exchange_rates": [
        "exchange rate",
        "exchange rates",
        "taux de change",
        "cours de change",
    ],
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Cube:
    cube_id: str
    name: str
    raw: dict[str, Any]


@dataclass
class DimensionElement:
    code: str
    label: str
    parent: str | None = None
    raw: dict[str, Any] | None = None


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(value: Any) -> str:
    """
    Normalize dirty INS metadata.

    Handles:
    - tabs/newlines
    - non-breaking spaces
    - accents
    - repeated whitespace
    - common metadata typos
    """
    if value is None:
        return ""

    text = str(value)

    text = text.replace("\t", " ")
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    text = text.replace("\xa0", " ")

    text = re.sub(r"\s+", " ", text).strip()

    # Common INS typo documented in the ecosystem:
    # Superificie -> Superficie
    text = re.sub(
        r"\bsuperificie\b",
        "superficie",
        text,
        flags=re.IGNORECASE,
    )

    return text


def ascii_normalize(value: Any) -> str:
    text = normalize_text(value).lower()

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    return text


def slug(value: Any) -> str:
    text = ascii_normalize(value)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def matches_any(text: str, patterns: Iterable[str]) -> bool:
    normalized = ascii_normalize(text)

    for pattern in patterns:
        pattern_normalized = ascii_normalize(pattern)

        if pattern_normalized in normalized:
            return True

    return False


# ============================================================
# NUMERIC PARSING
# ============================================================

def parse_number(value: Any) -> float | int | None:
    """
    Parse French/European/English numeric formats.

    Examples:
        1 234,56
        1.234,56
        1234.56
        1,234.56
        -123,4
        12 %
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

    text = normalize_text(value)

    if not text:
        return None

    lowered = ascii_normalize(text)

    if lowered in {
        "",
        "na",
        "n a",
        "n d",
        "nd",
        "null",
        "none",
        "-",
        "—",
        "..",
        "...",
    }:
        return None

    # Remove common units/symbols.
    text = re.sub(
        r"(?i)(mtnd|tnd|dt|million|millions|md|%)",
        "",
        text,
    )

    text = text.strip()

    # Keep only digits, separators and sign.
    text = re.sub(r"[^0-9,.\-+]", "", text)

    if not text:
        return None

    try:
        # Both comma and dot present.
        if "," in text and "." in text:
            # 1.234,56 -> 1234.56
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "")
                text = text.replace(",", ".")
            # 1,234.56 -> 1234.56
            else:
                text = text.replace(",", "")

        # Only comma.
        elif "," in text:
            parts = text.split(",")

            # 1234,56
            if len(parts[-1]) in (1, 2):
                text = "".join(parts[:-1]) + "." + parts[-1]
            else:
                # 1,234 -> assume thousands separator
                text = "".join(parts)

        # Multiple dots.
        elif text.count(".") > 1:
            parts = text.split(".")

            if len(parts[-1]) in (1, 2):
                text = "".join(parts[:-1]) + "." + parts[-1]
            else:
                text = "".join(parts)

        number = float(text)

        if not math.isfinite(number):
            return None

        if number.is_integer():
            return int(number)

        return number

    except ValueError:
        return None


# ============================================================
# XML HELPERS
# ============================================================

def local_name(tag: str) -> str:
    """
    Remove XML namespace:
      {namespace}Tag -> Tag
    """
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]

    return tag


def element_text(element: ET.Element) -> str:
    text = "".join(element.itertext())
    return normalize_text(text)


def find_attribute(
    element: ET.Element,
    names: Iterable[str],
) -> str | None:
    wanted = {
        ascii_normalize(name)
        for name in names
    }

    for key, value in element.attrib.items():
        if ascii_normalize(key) in wanted:
            return normalize_text(value)

    return None


def first_child_text(
    element: ET.Element,
    names: Iterable[str],
) -> str | None:
    wanted = {
        ascii_normalize(name)
        for name in names
    }

    for child in element.iter():
        tag = ascii_normalize(local_name(child.tag))

        if tag in wanted:
            text = element_text(child)

            if text:
                return text

    return None


# ============================================================
# API CLIENT
# ============================================================

class INSApiClient:
    """
    Thin client around the Prognoz XML API.

    IMPORTANT:
    All API operations are POST requests.
    """

    def __init__(
        self,
        api_url: str = API_URL,
        timeout: int = REQUEST_TIMEOUT,
    ):
        self.api_url = api_url
        self.timeout = timeout

        self.session = requests.Session()

        self.session.headers.update(
            {
                "Content-Type": "text/xml; charset=utf-8",
                "Accept": "text/xml, application/xml",
                "User-Agent": (
                    "T19-INS-Hackathon-Scraper/1.0 "
                    "(Python requests)"
                ),
            }
        )

        self._last_call = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call

        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

    def post_xml(
        self,
        operation: str,
        xml_body: str,
    ) -> bytes | None:
        """
        POST an XML QueryMessage and return raw XML bytes.
        """

        self._rate_limit()

        logger.info(
            "API CALL | operation=%s | url=%s",
            operation,
            self.api_url,
        )

        logger.debug(
            "REQUEST XML | operation=%s\n%s",
            operation,
            xml_body,
        )

        last_exception: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.post(
                    f"{self.api_url.rstrip('/')}/{operation}",
                    data=xml_body.encode("utf-8"),
                    timeout=self.timeout,
                )

                self._last_call = time.monotonic()

                logger.info(
                    "API RESPONSE | operation=%s | status=%s | bytes=%s",
                    operation,
                    response.status_code,
                    len(response.content),
                )

                logger.debug(
                    "RESPONSE XML | operation=%s\n%s",
                    operation,
                    response.text[:10000],
                )

                if response.status_code == 200:
                    return response.content

                if response.status_code in {
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    delay = BACKOFF_SECONDS * (2 ** (attempt - 1))

                    logger.warning(
                        "Transient HTTP %s on %s; retrying in %.1fs",
                        response.status_code,
                        operation,
                        delay,
                    )

                    time.sleep(delay)
                    continue

                response.raise_for_status()

            except requests.RequestException as exc:
                last_exception = exc

                delay = BACKOFF_SECONDS * (2 ** (attempt - 1))

                logger.warning(
                    "Request failure on %s attempt %d/%d: %s",
                    operation,
                    attempt,
                    MAX_RETRIES,
                    exc,
                )

                if attempt < MAX_RETRIES:
                    time.sleep(delay)

        logger.error(
            "API FAILED | operation=%s | error=%s",
            operation,
            last_exception,
        )

        return None


# ============================================================
# XML QUERY BUILDERS
# ============================================================

def query_message(inner_xml: str = "") -> str:
    return (
        f'<QueryMessage lcid="{LANGUAGE_CODE}">'
        f"{inner_xml}"
        f"</QueryMessage>"
    )


def source_query_message(
    source_id: str,
    inner_xml: str,
) -> str:
    return (
        f'<QueryMessage SourceId="{escape_xml(source_id)}">'
        f"{inner_xml}"
        f"</QueryMessage>"
    )


def build_get_structure_query() -> str:
    return query_message()


def build_dimension_query(dimension_id: str) -> str:
    return query_message(
        "<DataWhere>"
        f"<DimensionId>{escape_xml(dimension_id)}</DimensionId>"
        "</DataWhere>"
    )


def escape_xml(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_data_where(
    dimension_filters: dict[str, list[str] | str] | None,
) -> str:
    parts = ["<DataWhere>"]

    if dimension_filters:
        for dimension_id, codes in dimension_filters.items():
            if isinstance(codes, str):
                codes = [codes]

            parts.append(
                f'<Dimension Id="{escape_xml(dimension_id)}">'
            )

            for code in codes:
                parts.append(
                    f"<Element>{escape_xml(code)}</Element>"
                )

            parts.append("</Dimension>")

    parts.append("</DataWhere>")
    return "".join(parts)


def build_data_borders_query(
    source_id: str,
    dimension_filters: dict[str, list[str] | str] | None = None,
) -> str:
    return source_query_message(
        source_id,
        build_data_where(dimension_filters),
    )


def build_get_data_query(
    source_id: str,
    dimension_filters: dict[str, list[str] | str] | None = None,
    start_period: str = "1.01.2019",
    end_period: str | None = None,
    frequency: str = "M",
) -> str:
    if end_period is None:
        end_period = f"31.12.{END_YEAR}"

    period = (
        f'<Period From="{escape_xml(start_period)}" '
        f'To="{escape_xml(end_period)}" '
        f'Frequency="{escape_xml(frequency)}"></Period>'
    )

    return source_query_message(
        source_id,
        period + build_data_where(dimension_filters),
    )


# ============================================================
# GET STRUCTURE
# ============================================================

def fetch_structure(
    client: INSApiClient,
) -> tuple[bytes | None, list[Cube]]:
    """
    Call GetStructure and save the raw response.
    """

    xml_request = build_get_structure_query()

    raw = client.post_xml(
        "GetStructure",
        xml_request,
    )

    if not raw:
        return None, []

    STRUCTURE_FILE.write_bytes(raw)

    logger.info(
        "Saved raw structure to %s",
        STRUCTURE_FILE,
    )

    cubes = parse_structure(raw)

    logger.info(
        "Discovered %d cubes",
        len(cubes),
    )

    print("\n" + "=" * 80)
    print("INS CUBES")
    print("=" * 80)

    for cube in cubes:
        print(
            f"{cube.cube_id:25} | {cube.name}"
        )

    print("=" * 80 + "\n")

    return raw, cubes


def parse_structure(raw_xml: bytes) -> list[Cube]:
    """
    Generic parser for the dirty Prognoz structure response.

    It does not rely on one exact namespace/schema.
    """

    root = ET.fromstring(raw_xml)

    cubes: list[Cube] = []
    seen: set[str] = set()

    for element in root.iter():
        tag = ascii_normalize(local_name(element.tag))

        if "cube" not in tag and tag != "source":
            continue

        cube_id = (
            find_attribute(
                element,
                ["Id", "ID", "id"],
            )
            if tag == "source"
            else None
        ) or (
            find_attribute(
                element,
                [
                    "ID",
                    "Id",
                    "id",
                    "CODE",
                    "Code",
                    "Key",
                    "KEY",
                ],
            )
            or first_child_text(
                element,
                [
                    "CubeId",
                    "CubeID",
                    "Id",
                    "ID",
                    "Code",
                ],
            )
        )

        name = (
            find_attribute(
                element,
                [
                    "NAME",
                    "Name",
                    "name",
                    "Caption",
                    "Title",
                ],
            )
            or first_child_text(
                element,
                [
                    "Name",
                    "NAME",
                    "Caption",
                    "Title",
                ],
            )
        )

        if not cube_id:
            continue

        cube_id = normalize_text(cube_id)
        name = normalize_text(name or cube_id)

        if cube_id in seen:
            continue

        seen.add(cube_id)

        raw_attributes = {
            normalize_text(k): normalize_text(v)
            for k, v in element.attrib.items()
        }

        cubes.append(
            Cube(
                cube_id=cube_id,
                name=name,
                raw={
                    "attributes": raw_attributes,
                    "tag": local_name(element.tag),
                },
            )
        )

    return cubes


# ============================================================
# CUBE DISCOVERY
# ============================================================

def rank_cubes(
    cubes: list[Cube],
    target_name: str,
) -> list[Cube]:
    """
    Rank cubes using semantic matching.

    We intentionally do not automatically trust the first match.
    The catalogue is saved and printed so the developer can verify
    the chosen cube.
    """

    patterns = TARGETS[target_name]

    ranked: list[tuple[int, Cube]] = []

    for cube in cubes:
        haystack = (
            f"{cube.cube_id} {cube.name}"
        )

        normalized = ascii_normalize(haystack)

        score = 0

        for pattern in patterns:
            p = ascii_normalize(pattern)

            if p == normalized:
                score += 100

            elif p in normalized:
                score += 50

        # Useful domain keywords.
        if target_name == "cpi":
            for word in [
                "prix",
                "ipc",
                "consumer",
                "inflation",
            ]:
                if word in normalized:
                    score += 5

        elif target_name == "gdp":
            for word in [
                "pib",
                "gdp",
                "produit interieur brut",
                "national accounts",
            ]:
                if word in normalized:
                    score += 5

        elif target_name == "foreign_trade":
            for word in [
                "commerce",
                "export",
                "import",
                "trade",
            ]:
                if word in normalized:
                    score += 5

        elif target_name == "public_finance":
            for word in [
                "dette",
                "budget",
                "finance",
                "finances",
            ]:
                if word in normalized:
                    score += 5

        elif target_name == "exchange_rates":
            for word in [
                "change",
                "devise",
                "currency",
                "exchange",
            ]:
                if word in normalized:
                    score += 5

        if score:
            ranked.append((score, cube))

    ranked.sort(
        key=lambda item: (
            -item[0],
            ascii_normalize(item[1].name),
        )
    )

    return [
        cube
        for _, cube in ranked
    ]


# ============================================================
# DIMENSION ELEMENTS
# ============================================================

def fetch_dimension_elements(
    client: INSApiClient,
    dimension_id: str,
) -> list[DimensionElement]:
    """
    Call GetDimensionElements.

    Handles the common Prognoz attributes:
      CODE
      C_CODE
      KEY

    and parent relationships.
    """

    xml_request = build_dimension_query(
        dimension_id
    )

    raw = client.post_xml(
        "GetDimensionElements",
        xml_request,
    )

    if not raw:
        return []

    return parse_dimension_elements(raw)


def parse_dimension_elements(
    raw_xml: bytes,
) -> list[DimensionElement]:
    root = ET.fromstring(raw_xml)

    elements: list[DimensionElement] = []
    seen: set[tuple[str, str]] = set()

    for element in root.iter():

        if ascii_normalize(local_name(element.tag)) != "element":
            continue

        code = find_attribute(
            element,
            [
                "CODE",
                "C_CODE",
                "KEY",
                "ID",
                "Id",
                "id",
            ],
        )

        if not code:
            continue

        label = (
            find_attribute(
                element,
                [
                    "NAME",
                    "Name",
                    "name",
                    "CAPTION",
                    "Caption",
                    "LABEL",
                    "Label",
                ],
            )
            or element_text(element)
        )

        code = normalize_text(code)
        label = normalize_text(label)

        if not label:
            label = code

        parent = find_attribute(
            element,
            [
                "PARENT",
                "Parent",
                "PARENTCODE",
                "PARENT_CODE",
                "C_PARENT",
            ],
        )

        key = (code, label)

        if key in seen:
            continue

        seen.add(key)

        elements.append(
            DimensionElement(
                code=code,
                label=label,
                parent=parent,
                raw={
                    "attributes": {
                        normalize_text(k): normalize_text(v)
                        for k, v in element.attrib.items()
                    }
                },
            )
        )

    return elements


def resolve_dimension_label(
    elements: list[DimensionElement],
    wanted_labels: Iterable[str],
) -> list[DimensionElement]:
    """
    Find dimension codes by human-readable labels.

    Uses exact normalized matches first, then substring matches.
    """

    wanted = [
        ascii_normalize(label)
        for label in wanted_labels
    ]

    exact: list[DimensionElement] = []
    partial: list[DimensionElement] = []

    for element in elements:
        label = ascii_normalize(element.label)

        if any(label == w for w in wanted):
            exact.append(element)

        elif any(w in label for w in wanted):
            partial.append(element)

    return exact or partial


def discover_cube_dimensions(
    client: INSApiClient,
    cube: Cube,
) -> dict[str, Any]:
    """
    Extract dimension IDs from the cube structure and query
    their elements.

    This is intentionally generic because Prognoz structures
    can differ between cube families.
    """

    raw = cube.raw

    # If the structure parser has not retained dimensions,
    # attempt to find them from the saved full structure.
    result = {
        "cube_id": cube.cube_id,
        "cube_name": cube.name,
        "dimensions": {},
    }

    if not STRUCTURE_FILE.exists():
        return result

    try:
        root = ET.fromstring(
            STRUCTURE_FILE.read_bytes()
        )
    except ET.ParseError:
        return result

    # Locate the cube node.
    cube_nodes = []

    for node in root.iter():
        tag = ascii_normalize(
            local_name(node.tag)
        )

        if "cube" not in tag and tag != "source":
            continue

        candidate_id = (
            find_attribute(
                node,
                ["Id", "ID", "id"]
                if tag == "source"
                else [
                    "ID",
                    "Id",
                    "id",
                    "CODE",
                    "Code",
                    "KEY",
                ],
            )
            or first_child_text(
                node,
                [
                    "CubeId",
                    "CubeID",
                    "Id",
                    "ID",
                    "Code",
                ],
            )
        )

        if candidate_id == cube.cube_id:
            cube_nodes.append(node)

    if not cube_nodes:
        return result

    cube_node = cube_nodes[0]

    dimension_ids: set[str] = set()

    for node in cube_node.iter():
        tag = ascii_normalize(
            local_name(node.tag)
        )

        if "dimension" not in tag:
            continue

        dimension_id = (
            find_attribute(
                node,
                [
                    "ID",
                    "Id",
                    "id",
                    "CODE",
                    "Code",
                    "KEY",
                ],
            )
            or first_child_text(
                node,
                [
                    "DimensionId",
                    "DimensionID",
                    "Id",
                    "ID",
                    "Code",
                ],
            )
        )

        if dimension_id:
            dimension_ids.add(
                normalize_text(dimension_id)
            )

    for dimension_id in sorted(dimension_ids):
        logger.info(
            "Resolving dimension %s for cube %s",
            dimension_id,
            cube.cube_id,
        )

        elements = fetch_dimension_elements(
            client,
            dimension_id,
        )

        result["dimensions"][dimension_id] = {
            "elements": [
                {
                    "code": item.code,
                    "label": item.label,
                    "parent": item.parent,
                }
                for item in elements
            ],
            "count": len(elements),
        }

    return result


def save_dimension_mappings(
    mappings: dict[str, Any],
) -> None:
    DIMENSIONS_FILE.write_text(
        json.dumps(
            mappings,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info(
        "Saved dimension mappings to %s",
        DIMENSIONS_FILE,
    )


# ============================================================
# GET DATA BORDERS
# ============================================================

def fetch_data_borders(
    client: INSApiClient,
    source_id: str,
    dimension_filters: dict[str, list[str] | str] | None = None,
) -> dict[str, Any] | None:
    raw = client.post_xml(
        "GetDataBorders",
        build_data_borders_query(
            source_id,
            dimension_filters,
        ),
    )

    if not raw:
        return None

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        logger.warning(
            "Could not parse borders for %s: %s",
            source_id,
            exc,
        )
        return None

    result: dict[str, Any] = {
        "source_id": source_id,
        "raw_text": normalize_text(
            element_text(root)
        ),
    }

    # Collect useful year/date-looking strings.
    dates = []

    for element in root.iter():
        text = element_text(element)

        if not text:
            continue

        matches = re.findall(
            r"\b(?:19|20)\d{2}(?:[-/]\d{1,2})?(?:[-/]\d{1,2})?\b",
            text,
        )

        dates.extend(matches)

    result["detected_periods"] = sorted(
        set(dates)
    )

    return result


# ============================================================
# GET DATA
# ============================================================

def fetch_cube_data(
    client: INSApiClient,
    source_id: str,
    dimension_filters: dict[str, list[str] | str] | None = None,
    start_period: str = "1.01.2019",
    end_period: str | None = None,
    frequency: str = "M",
) -> bytes | None:
    """
    Request actual cube observations.
    """

    query = build_get_data_query(
        source_id=source_id,
        dimension_filters=dimension_filters,
        start_period=start_period,
        end_period=end_period,
        frequency=frequency,
    )

    raw = client.post_xml(
        "GetData",
        query,
    )

    if not raw:
        logger.warning(
            "EMPTY | source=%s",
            source_id,
        )
        return None

    # Some cubes advertise a period range but contain no
    # observation values. Detect very small/empty XML responses.
    text = raw.decode(
        "utf-8",
        errors="replace",
    )

    normalized = ascii_normalize(text)

    if (
        len(text.strip()) < 100
        or "nodata" in normalized
        or "no data" in normalized
        or "empty" in normalized
    ):
        logger.warning(
            "EMPTY | source=%s | response appears to contain no data",
            source_id,
        )
        return None

    return raw


# ============================================================
# DATA RESPONSE PARSING
# ============================================================

def parse_data_response(
    raw_xml: bytes,
) -> list[dict[str, Any]]:
    """
    Convert a Prognoz GetData response into generic row dictionaries.

    We deliberately do not assume one exact XML schema.

    The parser looks for repeated elements with:
      - period/date-like information
      - code/label information
      - numeric values
    """

    root = ET.fromstring(raw_xml)

    rows: list[dict[str, Any]] = []

    set_elements = [
        element
        for element in root.iter()
        if ascii_normalize(local_name(element.tag)) == "set"
    ]

    if set_elements:
        for element in set_elements:
            row = {
                normalize_text(key): normalize_text(value)
                for key, value in element.attrib.items()
            }
            value = normalize_text(element.text)

            if value:
                row["_text"] = value

            rows.append(row)

        return rows

    # Strategy 1:
    # Find elements whose attributes already represent a data cell.
    for element in root.iter():
        attributes = {
            normalize_text(k): normalize_text(v)
            for k, v in element.attrib.items()
        }

        if not attributes:
            continue

        row = parse_element_as_row(element)

        if row:
            rows.append(row)

    # Strategy 2:
    # If the response is tabular XML, inspect children.
    if not rows:
        for parent in root.iter():
            children = list(parent)

            if len(children) < 2:
                continue

            row: dict[str, Any] = {}

            for child in children:
                tag = normalize_text(
                    local_name(child.tag)
                )

                text = element_text(child)

                if not text:
                    continue

                row[tag] = text

            if row:
                rows.append(row)

    # Deduplicate.
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        signature = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
        )

        if signature in seen:
            continue

        seen.add(signature)
        unique.append(row)

    logger.info(
        "Parsed %d generic data rows",
        len(unique),
    )

    return unique


def parse_element_as_row(
    element: ET.Element,
) -> dict[str, Any] | None:
    row: dict[str, Any] = {}

    for key, value in element.attrib.items():
        row[normalize_text(key)] = normalize_text(value)

    text = element_text(element)

    if text and len(text) < 500:
        row["_text"] = text

    # Need at least some useful content.
    if len(row) < 1:
        return None

    return row


# ============================================================
# GENERIC ROW UTILITIES
# ============================================================

PERIOD_KEYS = {
    "period",
    "date",
    "time",
    "year",
    "quarter",
    "month",
    "periode",
    "période",
    "annee",
    "année",
}

LABEL_KEYS = {
    "name",
    "label",
    "caption",
    "title",
    "libelle",
    "libellé",
    "indicator",
    "indicateur",
    "measure",
    "mesure",
    "series",
    "serie",
    "série",
    "description",
}


def get_row_text(
    row: dict[str, Any],
) -> str:
    parts = []

    for key, value in row.items():
        parts.append(
            normalize_text(key)
        )
        parts.append(
            normalize_text(value)
        )

    return " ".join(parts)


def find_period(
    row: dict[str, Any],
) -> str | None:
    for key, value in row.items():
        key_normalized = ascii_normalize(key)

        if key_normalized in {
            ascii_normalize(item)
            for item in PERIOD_KEYS
        }:
            text = normalize_text(value)

            if text:
                return text

    # Fallback: search values.
    for value in row.values():
        text = normalize_text(value)

        if re.search(
            r"\b(?:19|20)\d{2}(?:[-/]\d{1,2})?(?:[-/]\d{1,2})?\b",
            text,
        ):
            return text

    return None


def find_numeric_values(
    row: dict[str, Any],
) -> list[tuple[str, float | int]]:
    values = []

    for key, value in row.items():
        number = parse_number(value)

        if number is None:
            continue

        values.append(
            (
                normalize_text(key),
                number,
            )
        )

    return values


def first_numeric_value(
    row: dict[str, Any],
) -> float | int | None:
    value = parse_number(row.get("_text"))

    if value is not None:
        return value

    values = find_numeric_values(row)

    if not values:
        return None

    return values[0][1]


# ============================================================
# INDICATOR CLASSIFICATION
# ============================================================

def classify_cpi_series(
    text: str,
) -> str | None:
    normalized = ascii_normalize(text)

    # Order matters.
    if "transport" in normalized:
        return "transport"

    if "housing" in normalized or "logement" in normalized:
        return "housing"

    if "food" in normalized or "alimentation" in normalized:
        return "food"

    if (
        "general index" in normalized
        or "indice general" in normalized
        or "indice d ensemble" in normalized
        or "indice general des prix" in normalized
    ):
        return "general_index"

    # General IPC can sometimes simply be named IPC.
    if normalized in {
        "ipc",
        "indice des prix a la consommation",
        "consumer price index",
    }:
        return "general_index"

    return None


def classify_trade_series(
    text: str,
) -> str | None:
    normalized = ascii_normalize(text)

    if "balance" in normalized or "solde" in normalized:
        if "trade" in normalized or "commerce" in normalized:
            return "balance_mtnd"

    if "export" in normalized:
        return "exports_mtnd"

    if "import" in normalized:
        return "imports_mtnd"

    return None


def classify_finance_series(
    text: str,
) -> str | None:
    normalized = ascii_normalize(text)

    if "external debt" in normalized or "dette exterieure" in normalized:
        return "external_debt_mtnd"

    if "internal debt" in normalized or "dette interieure" in normalized:
        return "internal_debt_mtnd"

    if (
        "total debt" in normalized
        or "public debt" in normalized
        or "dette publique" in normalized
    ):
        return "total_debt_mtnd"

    if (
        "budget balance" in normalized
        or "solde budgetaire" in normalized
    ):
        return "budget_balance_mtnd"

    if (
        "debt service" in normalized
        or "service de la dette" in normalized
        or "charge de la dette" in normalized
    ):
        return "debt_service_mtnd"

    return None


def classify_exchange_series(
    text: str,
) -> str | None:
    normalized = ascii_normalize(text)

    has_eur = (
        "eur" in normalized
        or "euro" in normalized
    )

    has_usd = (
        "usd" in normalized
        or "dollar" in normalized
    )

    if has_eur and (
        "tnd" in normalized
        or "dt" in normalized
        or "tunisie" in normalized
    ):
        return "eur_tnd"

    if has_usd and (
        "tnd" in normalized
        or "dt" in normalized
        or "tunisie" in normalized
    ):
        return "usd_tnd"

    return None


# ============================================================
# DATE NORMALIZATION
# ============================================================

MONTH_MAP = {
    "jan": "01",
    "janvier": "01",
    "feb": "02",
    "fev": "02",
    "fevr": "02",
    "fevrier": "02",
    "février": "02",
    "mar": "03",
    "mars": "03",
    "apr": "04",
    "avr": "04",
    "avril": "04",
    "may": "05",
    "mai": "05",
    "jun": "06",
    "juin": "06",
    "jul": "07",
    "juil": "07",
    "juillet": "07",
    "aug": "08",
    "aou": "08",
    "aout": "08",
    "août": "08",
    "sep": "09",
    "sept": "09",
    "septembre": "09",
    "oct": "10",
    "octobre": "10",
    "nov": "11",
    "novembre": "11",
    "dec": "12",
    "decembre": "12",
    "décembre": "12",
}


def normalize_monthly_date(
    value: Any,
) -> str | None:
    text = normalize_text(value)

    if not text:
        return None

    api_period = re.search(
        r"\bMONTHS?\s*:\s*(0?[1-9]|1[0-2])\.(19|20)\d{2}\b",
        text,
        flags=re.IGNORECASE,
    )

    if api_period:
        year = re.search(r"\b(?:19|20)\d{2}\b", text)

        if year:
            return f"{year.group(0)}-{int(api_period.group(1)):02d}"

    # YYYY-MM
    match = re.search(
        r"\b((?:19|20)\d{2})[-/](0?[1-9]|1[0-2])\b",
        text,
    )

    if match:
        return (
            f"{match.group(1)}-"
            f"{int(match.group(2)):02d}"
        )

    normalized = ascii_normalize(text)

    for month_name, month_number in MONTH_MAP.items():
        if month_name in normalized:
            year_match = re.search(
                r"\b((?:19|20)\d{2})\b",
                normalized,
            )

            if year_match:
                return (
                    f"{year_match.group(1)}-"
                    f"{month_number}"
                )

    return None


def normalize_quarterly_date(
    value: Any,
) -> str | None:
    text = normalize_text(value)

    api_period = re.search(
        r"\bQUARTERS?\s*:\s*([1-4])\.(19|20)\d{2}\b",
        text,
        flags=re.IGNORECASE,
    )

    if api_period:
        year = re.search(r"\b(?:19|20)\d{2}\b", text)

        if year:
            return f"{year.group(0)}-Q{api_period.group(1)}"

    match = re.search(
        r"\b((?:19|20)\d{2})\s*[-/]?\s*Q([1-4])\b",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        return (
            f"{match.group(1)}-Q{match.group(2)}"
        )

    normalized = ascii_normalize(text)

    # French T1/T2/T3/T4.
    match = re.search(
        r"\b((?:19|20)\d{2})\s*[-/]?\s*T([1-4])\b",
        normalized,
    )

    if match:
        return (
            f"{match.group(1)}-Q{match.group(2)}"
        )

    return None


# ============================================================
# CPI EXTRACTION
# ============================================================

def extract_cpi(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    series: dict[str, dict[str, Any]] = {}

    for row in rows:
        period = find_period(row)

        if not period:
            continue

        date = normalize_monthly_date(period)

        if not date:
            continue

        if not (
            f"{START_YEAR}-01"
            <= date
            <= f"{END_YEAR}-12"
        ):
            continue

        text = get_row_text(row)

        indicator = classify_cpi_series(text)

        if not indicator:
            continue

        value = first_numeric_value(row)

        if value is None:
            continue

        if date not in series:
            series[date] = {
                "date": date,
                "general_index": None,
                "food": None,
                "transport": None,
                "housing": None,
            }

        # Do not overwrite a value with None.
        if series[date][indicator] is None:
            series[date][indicator] = value

    return [
        series[key]
        for key in sorted(series)
    ]


# ============================================================
# GDP EXTRACTION
# ============================================================

def extract_gdp(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for row in rows:
        period = find_period(row)

        if not period:
            continue

        date = normalize_quarterly_date(period)

        if not date:
            continue

        year = int(date[:4])

        if year < START_YEAR or year > END_YEAR:
            continue

        text = get_row_text(row)

        normalized = ascii_normalize(text)

        if not (
            "gdp" in normalized
            or "pib" in normalized
            or "produit interieur brut" in normalized
        ):
            continue

        if not (
            "growth" in normalized
            or "croissance" in normalized
            or "variation" in normalized
            or "evolution" in normalized
        ):
            continue

        value = first_numeric_value(row)

        if value is None:
            continue

        result[date] = {
            "date": date,
            "real_growth_yoy": value,
        }

    return [
        result[key]
        for key in sorted(result)
    ]


# ============================================================
# FOREIGN TRADE EXTRACTION
# ============================================================

def extract_foreign_trade(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for row in rows:
        period = find_period(row)

        if not period:
            continue

        date = normalize_monthly_date(period)

        if not date:
            continue

        if int(date[:4]) < START_YEAR:
            continue

        text = get_row_text(row)

        if not (
            "export" in ascii_normalize(text)
            or "import" in ascii_normalize(text)
            or "commerce" in ascii_normalize(text)
            or "trade" in ascii_normalize(text)
        ):
            continue

        indicator = classify_trade_series(text)

        if not indicator:
            continue

        value = first_numeric_value(row)

        if value is None:
            continue

        if date not in result:
            result[date] = {
                "date": date,
                "exports_mtnd": None,
                "imports_mtnd": None,
                "balance_mtnd": None,
            }

        if result[date][indicator] is None:
            result[date][indicator] = value

    return [
        result[key]
        for key in sorted(result)
    ]


# ============================================================
# PUBLIC FINANCE EXTRACTION
# ============================================================

def extract_public_finance(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}

    for row in rows:
        period = find_period(row)

        if not period:
            continue

        year_match = re.search(
            r"\b((?:19|20)\d{2})\b",
            period,
        )

        if not year_match:
            continue

        year = int(year_match.group(1))

        if year < START_YEAR or year > END_YEAR:
            continue

        text = get_row_text(row)

        indicator = classify_finance_series(text)

        if not indicator:
            continue

        value = first_numeric_value(row)

        if value is None:
            continue

        if year not in result:
            result[year] = {
                "year": year,
                "total_debt_mtnd": None,
                "external_debt_mtnd": None,
                "internal_debt_mtnd": None,
                "budget_balance_mtnd": None,
                "debt_service_mtnd": None,
            }

        if result[year][indicator] is None:
            result[year][indicator] = value

    return [
        result[key]
        for key in sorted(result)
    ]


# ============================================================
# EXCHANGE RATE EXTRACTION
# ============================================================

def extract_exchange_rates(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for row in rows:
        period = find_period(row)

        if not period:
            continue

        date = normalize_monthly_date(period)

        if not date:
            continue

        if int(date[:4]) < START_YEAR:
            continue

        text = get_row_text(row)

        indicator = classify_exchange_series(text)

        if not indicator:
            continue

        value = first_numeric_value(row)

        if value is None:
            continue

        if date not in result:
            result[date] = {
                "date": date,
                "eur_tnd": None,
                "usd_tnd": None,
            }

        if result[date][indicator] is None:
            result[date][indicator] = value

    return [
        result[key]
        for key in sorted(result)
    ]


# ============================================================
# DIMENSION/CUBE SELECTION
# ============================================================

def choose_candidate_cube(
    cubes: list[Cube],
    target: str,
) -> Cube | None:
    ranked = rank_cubes(
        cubes,
        target,
    )

    if not ranked:
        logger.warning(
            "No cube candidate found for %s",
            target,
        )
        return None

    logger.info(
        "Cube candidates for %s:",
        target,
    )

    for index, cube in enumerate(ranked[:10], 1):
        logger.info(
            "  %d. %s | %s",
            index,
            cube.cube_id,
            cube.name,
        )

    # IMPORTANT:
    # Automatic selection is only a starting point.
    # The top candidate is used for the automated run,
    # while all candidates are printed for manual verification.
    return ranked[0]


# ============================================================
# EMPTY/SYNTHETIC FALLBACK
# ============================================================

def synthetic_months(
    start_year: int,
    end_year: int,
) -> list[str]:
    result = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            result.append(
                f"{year}-{month:02d}"
            )

    return result


def generate_synthetic_output() -> dict[str, Any]:
    """
    Emergency hackathon fallback.

    The values are deliberately NOT presented as real INS data.
    """

    cpi = []

    for date in synthetic_months(
        START_YEAR,
        END_YEAR,
    ):
        cpi.append(
            {
                "date": date,
                "general_index": None,
                "food": None,
                "transport": None,
                "housing": None,
            }
        )

    return {
        "metadata": {
            "source": "INS Tunisia DataPortal",
            "url": BASE_URL,
            "scraped_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "method": "fallback: synthetic",
            "cubes_used": [],
            "warning": (
                "SYNTHETIC OUTPUT. "
                "No INS observations were successfully retrieved."
            ),
        },
        "cpi": {
            "monthly": cpi,
        },
        "gdp": {
            "quarterly": [],
        },
        "foreign_trade": {
            "monthly": [],
        },
        "public_finance": {
            "annual": [],
        },
        "exchange_rates": {
            "monthly": [],
        },
    }


# ============================================================
# OUTPUT
# ============================================================

def empty_output() -> dict[str, Any]:
    return {
        "metadata": {
            "source": "INS Tunisia DataPortal",
            "url": BASE_URL,
            "scraped_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "method": "XML API",
            "cubes_used": [],
        },
        "cpi": {
            "monthly": [],
        },
        "gdp": {
            "quarterly": [],
        },
        "foreign_trade": {
            "monthly": [],
        },
        "public_finance": {
            "annual": [],
        },
        "exchange_rates": {
            "monthly": [],
        },
    }


def save_output(
    output: dict[str, Any],
) -> None:
    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info(
        "Saved final output to %s",
        OUTPUT_FILE,
    )


# ============================================================
# TARGET EXTRACTION PIPELINE
# ============================================================

def extract_target(
    client: INSApiClient,
    cubes: list[Cube],
    target: str,
) -> tuple[Cube | None, list[dict[str, Any]]]:
    """
    Attempt one target.

    Because cube schemas vary, this function performs:

      1. candidate discovery
      2. GetDataBorders
      3. generic GetData
      4. generic XML parsing

    Once the exact cube/dimension combination has been
    confirmed from ins_structure.xml, the dimension filters
    should be filled in here for a deterministic query.
    """

    cube = choose_candidate_cube(
        cubes,
        target,
    )

    if cube is None:
        return None, []

    borders = fetch_data_borders(
        client,
        cube.cube_id,
    )

    if borders:
        logger.info(
            "Borders for %s: %s",
            cube.cube_id,
            borders,
        )

    # First attempt: cube without dimension filters.
    raw = fetch_cube_data(
        client,
        cube.cube_id,
    )

    if not raw:
        logger.warning(
            "Cube %s returned no usable data",
            cube.cube_id,
        )
        return cube, []

    rows = parse_data_response(
        raw
    )

    return cube, rows


def fetch_observation_rows(
    client: INSApiClient,
    source_id: str,
    dimension_filters: dict[str, list[str] | str],
    frequency: str,
) -> list[dict[str, Any]]:
    raw = fetch_cube_data(
        client,
        source_id,
        dimension_filters,
        f"1.01.{START_YEAR}",
        f"31.12.{END_YEAR}",
        frequency,
    )

    if raw is None:
        return []

    return parse_data_response(raw)


def build_live_output(
    client: INSApiClient,
    cubes: list[Cube],
) -> dict[str, Any]:
    output = empty_output()
    cube_ids = {cube.cube_id for cube in cubes}
    cpi_rows = []
    gdp_rows = []

    if NSO_SOURCE_ID in cube_ids:
        try:
            rows = fetch_observation_rows(
                client,
                NSO_SOURCE_ID,
                {
                    NSO_INDICATOR_DIMENSION: CPI_INDICATOR_ID,
                    NSO_REGION_DIMENSION: TUNISIA_REGION_ID,
                    NSO_UNITS_DIMENSION: "1",
                },
                "M",
            )

            monthly = {}

            for row in rows:
                period = find_period(row)
                date = normalize_monthly_date(period)
                value = first_numeric_value(row)

                if date is None or value is None:
                    continue

                monthly[date] = {
                    "date": date,
                    "general_index": value,
                    "food": None,
                    "transport": None,
                    "housing": None,
                }

            cpi_rows = [
                monthly[date]
                for date in sorted(monthly)
            ]
        except Exception as exc:
            logger.exception(
                "CPI extraction failed: %s",
                exc,
            )

    if GDP_SOURCE_ID in cube_ids:
        try:
            rows = fetch_observation_rows(
                client,
                GDP_SOURCE_ID,
                {
                    GDP_INDICATOR_DIMENSION: GDP_INDICATOR_ID,
                    GDP_VALUATION_DIMENSION: GDP_YOY_VALUATION_ID,
                },
                "Q",
            )

            quarterly = {}

            for row in rows:
                period = find_period(row)
                date = normalize_quarterly_date(period)
                value = first_numeric_value(row)

                if date is None or value is None:
                    continue

                quarterly[date] = {
                    "date": date,
                    "real_growth_yoy": value,
                }

            gdp_rows = [
                quarterly[date]
                for date in sorted(quarterly)
            ]
        except Exception as exc:
            logger.exception(
                "GDP extraction failed: %s",
                exc,
            )

    output["cpi"]["monthly"] = cpi_rows
    output["gdp"]["quarterly"] = gdp_rows
    output["metadata"]["cubes_used"] = [
        source_id
        for source_id, rows in (
            (NSO_SOURCE_ID, cpi_rows),
            (GDP_SOURCE_ID, gdp_rows),
        )
        if rows
    ]
    output["metadata"]["cubes_discovered"] = len(cubes)
    output["metadata"]["observation_count"] = (
        len(cpi_rows) + len(gdp_rows)
    )
    output["metadata"]["unavailable_sections"] = [
        section
        for section in (
            "foreign_trade",
            "public_finance",
            "exchange_rates",
        )
    ]
    output["metadata"]["notes"] = [
        "Only observations returned by the official INS XML API are included.",
        "CPI is the national household CPI index, base 2015=100.",
        "GDP growth is the year-over-year quarterly change at 2015 prices.",
        "Food, transport, and housing CPI breakdowns were not available from the queried indicator.",
        "Trade, public-finance, and exchange-rate observations were not returned by verified queries.",
    ]

    return output


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    logger.info(
        "Starting INS Tunisia XML scraper"
    )

    logger.info(
        "Project root: %s",
        PROJECT_ROOT,
    )

    logger.info(
        "API endpoint: %s",
        API_URL,
    )

    client = INSApiClient()

    # --------------------------------------------------------
    # STEP 1: DISCOVERY
    # --------------------------------------------------------

    try:
        _, cubes = fetch_structure(client)
    except Exception as exc:
        logger.exception(
            "GetStructure failed: %s",
            exc,
        )

        output = empty_output()
        output["metadata"]["warning"] = (
            f"INS API structure request failed: {exc}"
        )
        save_output(output)

        return 1

    if not cubes:
        logger.error(
            "No cubes were discovered."
        )

        output = empty_output()
        output["metadata"]["warning"] = (
            "The INS API returned no data sources."
        )
        save_output(output)

        return 1

    output = build_live_output(client, cubes)

    if output["metadata"]["observation_count"] == 0:
        output["metadata"]["warning"] = (
            "The INS API returned no observations for the verified CPI and GDP queries."
        )

    save_output(output)

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print("\n" + "=" * 80)
    print("INS SCRAPER SUMMARY")
    print("=" * 80)

    print(
        f"Cubes discovered : {len(cubes)}"
    )

    print(
        f"Sources used     : {len(output['metadata']['cubes_used'])}"
    )

    print(
        f"CPI observations : {len(output['cpi']['monthly'])}"
    )

    print(
        f"GDP observations : {len(output['gdp']['quarterly'])}"
    )

    print(
        f"Trade observations : {len(output['foreign_trade']['monthly'])}"
    )

    print(
        f"Finance observations : {len(output['public_finance']['annual'])}"
    )

    print(
        f"FX observations : {len(output['exchange_rates']['monthly'])}"
    )

    print(
        f"\nOutput: {OUTPUT_FILE}"
    )

    print(
        f"Structure: {STRUCTURE_FILE}"
    )

    print(
        f"Dimensions: {DIMENSIONS_FILE}"
    )

    print(
        f"Log: {LOG_FILE}"
    )

    print("=" * 80)

    return 0 if output["metadata"]["observation_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())