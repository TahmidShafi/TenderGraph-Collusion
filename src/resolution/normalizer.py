"""Supplier name normalization, corporate suffix stripping, and agency filtering.

Provides deterministic cleaning for supplier entity resolution, excluding
non-commercial placeholders and state-owned implementing agencies/utilities
erroneously recorded as suppliers in World Bank procurement data.
"""

from __future__ import annotations

import re
from typing import Final

from src.ingestion.wb_fetcher import CANONICAL_AGENCY_PATTERNS

# Corporate prefixes to strip from company names
CORPORATE_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:M/S\.?|MESSRS\.?|M/S|THE)\s+",
    re.IGNORECASE,
)

# Corporate suffixes to strip from company names (applied iteratively)
CORPORATE_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:PVT\.?\s+LTD\.?|PRIVATE\s+LIMITED|LTD\.?|LIMITED|PVT\.?|PRIVATE|"
    r"INC\.?|INCORPORATED|CORP\.?|CORPORATION|CO\.?|COMPANY|JV|JOINT\s+VENTURE|"
    r"LLC|PLC|ENTERPRISE|ENTERPRISES)\b",
    re.IGNORECASE,
)

# Placeholder supplier names that do not represent commercial firms
NON_COMMERCIAL_PLACEHOLDERS: Final[list[str]] = [
    r"\bINDIVIDUAL\s+CONSULTANT\b",
    r"\bINDIVIDUAL\s+CONSULTANTS\b",
    r"\bINDIVIDUAL\b",
    r"\bMULTIPLE\s+SUPPLIERS\b",
    r"\bVARIOUS\b",
    r"\bUNKNOWN\b",
    r"\bNOT\s+REPORTED\b",
    r"\bNOT\s+ELIGIBLE\b",
    r"\bUNSPECIFIED\b",
]

# Explicit state-owned agencies, utility corporations, and government directorates
# erroneously recorded as commercial suppliers
STATE_AGENCY_SUPPLIER_PATTERNS: Final[list[str]] = [
    r"\bPOWER\s+GRID\s+COMPANY\s+OF\s+BANGLADESH\b",
    r"\bLOCAL\s+GOVERNMENT\s+ENGINEERING\s+DEPARTMENT\b",
    r"\bROADS\s+AND\s+HIGHWAYS\b",
    r"\bBANGLADESH\s+WATER\s+DEVELOPMENT\s+BOARD\b",
    r"\bDEPARTMENT\s+OF\s+PUBLIC\s+HEALTH\s+ENGINEERING\b",
    r"\bBANGLADESH\s+POWER\s+DEVELOPMENT\s+BOARD\b",
    r"\bBANGLADESH\s+RURAL\s+ELECTRIFICATION\s+BOARD\b",
    r"\bWATER\s+SUPPLY\s+(?:AND|&)\s+SEWERAGE\b",
    r"\b(?:NATIONAL|DHAKA|CHITTAGONG|KHULNA|RAJSHAHI)\s+WATER\s+AND\s+SEWERAGE\b",
    r"\b(?:DHAKA|CHITTAGONG|KHULNA|RAJSHAHI)\s+WASA\b",
    r"\bBANGLADESH\s+RAILWAY\b",
    r"\bBANGLADESH\s+BUREAU\s+OF\s+STATISTICS\b",
    r"\bBANGLADESH\s+COMPUTER\s+COUNCIL\b",
    r"\bINFRASTRUCTURE\s+DEVELOPMENT\s+COMPANY\s+LIMITED\b",
    r"\bMINISTRY\s+OF\b",
    r"\bDIRECTORATE\s+GENERAL\s+OF\b",
    r"\bDIRECTORATE\s+OF\b",
    r"\bDEPARTMENT\s+OF\s+(?:ZOOLOGY|CIVIL|GEOGRAPHY|DISASTER|ENVIRONMENT|LIVESTOCK|YOUTH|SOCIAL|FISHERIES|AGRICULTURAL)\b",
    r"^\s*(?:LGED|PGCB|RHD|BWDB|DPHE|BPDB|BREB|DWASA|CWASA|BBS|IDCOL)\s*$",
    r"\b(LGED|PGCB|RHD|BWDB|DPHE|BPDB|BREB|DWASA|CWASA)\b(?:\s*\(|\s*,|\s*$)",
]

# Common generic first-tokens in South Asia that require second-token disambiguation
GENERIC_INITIAL_TOKENS: Final[set[str]] = {
    "MD",
    "MOHAMMAD",
    "MOHAMED",
    "MST",
    "MR",
    "DR",
    "ENGR",
}


def clean_supplier_name(raw_name: str) -> str:
    """Deterministically clean and standardize a raw supplier firm name.

    Applies:
    1. Case normalization to uppercase.
    2. Stripping corporate prefixes ('M/S', 'Messrs', 'The').
    3. Iteratively stripping corporate suffixes ('LTD', 'PVT LTD', 'INC', 'CO', 'JV').
    4. Normalizing ampersands ('&' -> 'AND') and removing punctuation/special characters.
    5. Stripping trailing trailing conjunctions or leftover suffixes.
    6. Collapsing whitespace and trimming.

    Args:
        raw_name: Raw supplier firm name string.

    Returns:
        Cleaned, normalized supplier firm name.
    """
    if not raw_name:
        return ""

    s = raw_name.upper().strip()

    # 1. Strip corporate prefixes
    s = CORPORATE_PREFIX_RE.sub("", s).strip()

    # 2. Iteratively strip corporate suffixes
    prev = None
    while prev != s:
        prev = s
        s = CORPORATE_SUFFIX_RE.sub("", s).strip()

    # 3. Standardize ampersand
    s = s.replace("&", " AND ")

    # 4. Standardize punctuation to spaces
    s = re.sub(r"[^A-Z0-9\s]", " ", s)

    # 5. Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    # 6. Final pass on trailing suffixes or trailing conjunctions
    prev = None
    while prev != s:
        prev = s
        s = re.sub(
            r"\b(?:PVT\s+LTD|PVT|LTD|LIMITED|PRIVATE|INC|CORP|CORPORATION|CO|COMPANY|JV|JOINT\s+VENTURE|ENTERPRISE|ENTERPRISES|AND)\s*$",
            "",
            s,
        ).strip()

    return s


def is_commercial_supplier(raw_name: str) -> bool:
    """Determine whether a supplier name represents a legitimate commercial entity.

    Excludes:
    - Non-commercial placeholders (e.g., 'INDIVIDUAL CONSULTANT', 'MULTIPLE SUPPLIERS').
    - State-owned implementing agencies and utility boards erroneously recorded
      as suppliers (e.g., 'POWER GRID COMPANY OF BANGLADESH', 'WATER SUPPLY & SEWERAGE',
      'LOCAL GOVERNMENT ENGINEERING DEPARTMENT').

    Args:
        raw_name: Raw or partially cleaned supplier string.

    Returns:
        True if the supplier is an eligible commercial vendor; False otherwise.
    """
    if not raw_name:
        return False

    name_upper = raw_name.upper().strip()

    # Check non-commercial placeholders
    for pat in NON_COMMERCIAL_PLACEHOLDERS:
        if re.search(pat, name_upper, re.IGNORECASE):
            return False

    # Check explicit state agency / utility patterns
    for pat in STATE_AGENCY_SUPPLIER_PATTERNS:
        if re.search(pat, name_upper, re.IGNORECASE):
            return False

    # Check canonical implementing agencies
    for pat, canonical in CANONICAL_AGENCY_PATTERNS:
        # Match only high-confidence agency names or full terms
        if len(canonical) >= 3 and canonical in {"LGED", "PGCB", "RHD", "BWDB", "DPHE", "BPDB", "BREB", "DWASA", "CWASA", "BBS", "IDCOL"}:
            if re.search(pat, name_upper, re.IGNORECASE):
                # Ensure we don't exclude commercial firms that merely include a word like 'STEP' or 'BARI'
                if canonical == "LGED" or "POWER GRID" in name_upper or "WATER SUPPLY" in name_upper:
                    return False
                if re.search(rf"\b{canonical}\b", name_upper):
                    return False

    return True


def get_blocking_token(clean_name: str) -> str:
    """Extract a blocking key from a cleaned supplier name.

    Handles:
    - Initial personal prefixes (e.g., 'MD RAHIM' -> 'MD_RAHI').
    - Single-letter initials (e.g., 'A M TRADERS' -> 'A_M').
    - Distinctive first 4 characters of the leading token.

    Args:
        clean_name: Cleaned supplier firm name.

    Returns:
        Blocking string token for candidate pair grouping.
    """
    tokens = clean_name.split()
    if not tokens:
        return "UNK"

    # Common South Asian honorific/initial prefix followed by primary personal name
    if tokens[0] in GENERIC_INITIAL_TOKENS and len(tokens) > 1:
        next_tok = tokens[1][:4] if len(tokens[1]) >= 4 else tokens[1]
        return f"{tokens[0]}_{next_tok}"

    # Single-letter initial followed by second initial or word
    if len(tokens[0]) == 1 and len(tokens) > 1:
        next_tok = tokens[1][:4] if len(tokens[1]) >= 4 else tokens[1]
        return f"{tokens[0]}_{next_tok}"

    # Standard first-token prefix
    return tokens[0][:4] if len(tokens[0]) >= 4 else tokens[0]
