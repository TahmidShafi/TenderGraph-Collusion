"""World Bank procurement contract and project metadata ingestion module.

Fetches Bangladesh records across the three procurement windows:
  1. Legacy FY2001-2016 (0037797)
  2. STEP FY2017-2019 (0066876)
  3. STEP Since-FY2020 (DS00005)

Also queries the World Bank Projects API to extract implementing agency and
sector/practice metadata, normalizes agency names into canonical abbreviations
(e.g., LGED, RHD, BWDB, DPHE, BPDB, PGCB), and provides local CSV/JSON cache
fallbacks in `data/raw/`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import time
from typing import Any
import httpx
from pydantic import ValidationError

from src.ingestion.db import DEFAULT_DB_PATH, get_connection
from src.ingestion.schemas import ProjectAgencyMap, RawWBContract

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
CONTRACTS_CACHE_FILE = DATA_RAW_DIR / "wb_contracts_bangladesh.json"
PROJECTS_CACHE_FILE = DATA_RAW_DIR / "wb_projects_bangladesh.json"

PROJECTS_API_URL = "https://search.worldbank.org/api/v2/projects?countrycode_exact=BD&format=json&rows=500"
CONTRACTS_API_URL = "https://search.worldbank.org/api/contractdata"

# Canonical implementing agency mapping rules for Bangladesh public sector
CANONICAL_AGENCY_PATTERNS: list[tuple[str, str]] = [
    (r"\b(LGED|Local Government Engineering Department|Rural Transport|Municipal Services|Urban and Territorial Development|Resilient Infrastructure for Adaptation|Sustainable Recovery, Emergency Preparedness|Host and Rohingya Enhancement|Emergency 2007 Cyclone)\b", "LGED"),
    (r"\b(RHD|Roads and Highways? Department|Road Rehabilitation and Maintenance|Bridge Improvement|Western Economic Corridor)\b", "RHD"),
    (r"\b(BWDB|Bangladesh Water Development Board|Water Development Board|Coastal Embankment|River Bank Protection|Flood Action|Water Management Improvement|Jamuna River)\b", "BWDB"),
    (r"\b(DPHE|Department of Public Health Engineering|Arsenic Mitigation|Water Supply Program)\b", "DPHE"),
    (r"\b(BPDB|Bangladesh Power Development Board|Power Development Board|Siddhirganj Power|Clean Fuel and Electric|Power Sector Development|Rural Electricity)\b", "BPDB"),
    (r"\b(PGCB|Power Grid Company of Bangladesh|Power System Reliability)\b", "PGCB"),
    (r"\b(BREB|REB|Bangladesh Rural Electrification Board|Rural Electrification Board|Rural Electrification and Renewable Energy)\b", "BREB"),
    (r"\b(BIWTA|Bangladesh Inland Water Transport Authority|Inland Water Transport)\b", "BIWTA"),
    (r"\b(BEZA|Bangladesh Economic Zones Authority|Private Investment & Digital Entrepreneurship)\b", "BEZA"),
    (r"\b(BEPZA|Bangladesh Export Processing Zones Authority)\b", "BEPZA"),
    (r"\b(BHTPA|Bangladesh Hi-?Tech Park Authority)\b", "BHTPA"),
    (r"\b(CWASA|Chattogram Water Supply and Sewerage Authority|Chittagong WASA)\b", "CWASA"),
    (r"\b(DWASA|Dhaka Water Supply and Sewerage Authority|Dhaka WASA|Dhaka Water Supply)\b", "DWASA"),
    (r"\b(KWASA|Khulna Water Supply and Sewerage Authority|Khulna WASA)\b", "KWASA"),
    (r"\b(RWASA|Rajshahi Water Supply and Sewerage Authority|Rajshahi WASA)\b", "RWASA"),
    (r"\b(DNCC|Dhaka North City Corporation|Urban Resilience Project)\b", "DNCC"),
    (r"\b(DSCC|Dhaka South City Corporation)\b", "DSCC"),
    (r"\b(CCPC|Chittagong City Corporation)\b", "CCPC"),
    (r"\b(DTCA|Dhaka Urban Transport|Transport Coordination Authority)\b", "DTCA"),
    (r"\b(MOHFW|Ministry of Health and Family Welfare|Health Nutrition and Population|Health and Population Program|National Nutrition|Integrated Nutrition|Health Sector Support|COVID-19 Emergency Response|Urban Health, Nutrition)\b", "MOHFW"),
    (r"\b(DGHS|Directorate General of Health Services)\b", "DGHS"),
    (r"\b(DGFP|Directorate General of Family Planning)\b", "DGFP"),
    (r"\b(DPE|Directorate of Primary Education|Primary Education Development|Reaching Out-of-School Children|ROSC|Primary Education|Out of School Children)\b", "DPE"),
    (r"\b(DSHE|Directorate of Secondary and Higher Education|Directorate of Secondary & Higher Education|Secondary Education Quality|SEQAEP|Female Secondary School|Learning Acceleration in Secondary)\b", "DSHE"),
    (r"\b(DTE|Directorate of Technical Education|Skills and Training Enhancement|STEP|ASSET|Accelerating and Strengthening Skills)\b", "DTE"),
    (r"\b(UGC|University Grants Commission|Higher Education Quality Enhancement|HEQEP|HEAT|Higher Education Acceleration)\b", "UGC"),
    (r"\b(MIN_LAW|Legal and Judicial Capacity Building|Ministry of Law)\b", "MIN_LAW"),
    (r"\b(IDCOL|Infrastructure Development Company Limited|Private Sector Infrastructure Development)\b", "IDCOL"),
    (r"\b(SDF|Social Development Foundation|Social Investment Program|Nuton Jibon)\b", "SDF"),
    (r"\b(DOF|Department of Fisheries|Fourth Fisheries|Sustainable Coastal and Marine Fisheries)\b", "DOF"),
    (r"\b(DAE|Department of Agricultural Extension|National Agricultural Technology)\b", "DAE"),
    (r"\b(BADC|Bangladesh Agricultural Development Corporation)\b", "BADC"),
    (r"\b(BFD|Bangladesh Forest Department|Forest Department|Sustainable Forests and Livelihoods)\b", "BFD"),
    (r"\b(PWD|Public Works Department)\b", "PWD"),
    (r"\b(BBS|Bangladesh Bureau of Statistics|National Strategy for Development of Statistics)\b", "BBS"),
    (r"\b(BB|Bangladesh Bank|Central Bank Strengthening|Enterprise Growth & Bank Modernization|Financial Sector Support)\b", "BB"),
    (r"\b(BCC|Bangladesh Computer Council|Leveraging ICT)\b", "BCC"),
    (r"\b(IMED|Implementation Monitoring and Evaluation Division|Public Procurement Reform|PPRP|DIMAPP|Strengthening Institutions for Transparency)\b", "IMED"),
    (r"\b(ERD|Economic Relations Division)\b", "ERD"),
    (r"\b(DDM|Department of Disaster Management|Safety Net Systems for the Poorest|SNSP)\b", "DDM"),
    (r"\b(DOE|Department of Environment|Clean Air and Sustainable Environment|Air Quality Management)\b", "DOE"),
    (r"\b(MOWCA|Ministry of Women and Children Affairs|Inclusive Services and Opportunities)\b", "MOWCA"),
    (r"\b(BLPA|Bangladesh Land Port Authority|Accelerating Transport and Trade Connectivity)\b", "BLPA"),
    (r"\b(DLS|Department of Livestock Services|Livestock and Dairy Development)\b", "DLS"),
    (r"\b(NHA|National Housing Authority|Low Income Community Housing)\b", "NHA"),
    (r"\b(PKSF|Palli Karma-Sahayak Foundation|Recovery and Advancement of Informal Sector)\b", "PKSF"),
    (r"\b(DYD|Department of Youth Development|Economic Acceleration and Resilience for NEET|EARN)\b", "DYD"),
    (r"\b(MOC|Ministry of Commerce|Export Competitiveness for Jobs|Export Diversification)\b", "MOC"),
    (r"\b(IDRA|Insurance Development and Regulatory Authority|Insurance Sector Development)\b", "IDRA"),
    (r"\b(DG_FOOD|Directorate General of Food|Modern Food Storage)\b", "DG_FOOD"),
    (r"\b(DSS|Department of Social Services|Cash Transfer Modernization)\b", "DSS"),
    (r"\b(LGD|Local Government Division|Local Governance Support|Income Support Program for the Poorest)\b", "LGD"),
    (r"\b(BR|Bangladesh Railway|Railway Department)\b", "BR"),
    (r"\b(BRTA|Bangladesh Road Transport Authority)\b", "BRTA"),
    (r"\b(SREDA|Sustainable and Renewable Energy Development Authority)\b", "SREDA"),
    (r"\b(BIDA|Bangladesh Investment Development Authority)\b", "BIDA"),
    (r"\b(BARI|Bangladesh Agricultural Research Institute)\b", "BARI"),
    (r"\b(BRRI|Bangladesh Rice Research Institute)\b", "BRRI"),
    (r"\b(BMDA|Barind Multipurpose Development Authority)\b", "BMDA"),
    (r"\b(BIWTC|Bangladesh Inland Water Transport Corporation)\b", "BIWTC"),
    (r"\b(CPA|Chittagong Port Authority)\b", "CPA"),
    (r"\b(MPA|Mongla Port Authority)\b", "MPA"),
    (r"\b(PPA|Payra Port Authority)\b", "PPA"),
]


def normalize_agency(
    raw_agency: str | None,
    project_name: str | None = None,
) -> str:
    """Normalize a raw implementing agency or project title into a canonical identifier.

    Args:
        raw_agency: Raw string from World Bank project metadata.
        project_name: Optional project title to resolve unmapped executing agencies.

    Returns:
        Canonical agency name (e.g., 'LGED', 'RHD', 'BWDB', 'UNKNOWN').
    """
    # 1. First test raw agency string
    if raw_agency:
        cleaned = raw_agency.strip()
        if cleaned and cleaned != "NOT_REPORTED":
            for pattern, canonical in CANONICAL_AGENCY_PATTERNS:
                if re.search(pattern, cleaned, re.IGNORECASE):
                    return canonical
            match = re.search(r"\(([A-Z]{2,10})\)", cleaned)
            if match:
                return match.group(1)

    # 2. If raw agency is missing/unknown, test project name against canonical patterns
    if project_name:
        cleaned_proj = project_name.strip()
        for pattern, canonical in CANONICAL_AGENCY_PATTERNS:
            if re.search(pattern, cleaned_proj, re.IGNORECASE):
                return canonical

    # 3. Fallback to slug if raw_agency exists
    if raw_agency:
        cleaned = raw_agency.strip()
        if cleaned and cleaned != "NOT_REPORTED":
            slug = re.sub(r"[^A-Za-z0-9]+", "_", cleaned).strip("_").upper()
            return slug[:40] if slug else "UNKNOWN"

    return "UNKNOWN"


def extract_global_practice(project_dict: dict[str, Any]) -> str:
    """Extract and standardize World Bank Global Practice or Sector.

    Args:
        project_dict: Raw project dictionary from World Bank Projects API.

    Returns:
        Standardized sector/practice label (e.g., 'Transport', 'Water', 'Energy').
    """
    sector1 = project_dict.get("sector1")
    if isinstance(sector1, dict) and sector1.get("Name"):
        name = str(sector1["Name"])
    else:
        name = str(project_dict.get("sector") or project_dict.get("mjtheme_namecode") or "General Procurement")

    # Group common sectors into Global Practices
    name_lower = name.lower()
    if any(k in name_lower for k in ["transport", "road", "railway", "highway", "bridge"]):
        return "Transport"
    if any(k in name_lower for k in ["water supply", "sanitation", "waste", "drainage"]):
        return "Water"
    if any(k in name_lower for k in ["energy", "power", "electric", "renewable"]):
        return "Energy"
    if any(k in name_lower for k in ["agricultur", "rural", "irrigation", "fisheries", "livestock"]):
        return "Agriculture"
    if any(k in name_lower for k in ["urban", "municipality", "city"]):
        return "Urban & Resilience"
    if any(k in name_lower for k in ["education", "school", "university", "vocational"]):
        return "Education"
    if any(k in name_lower for k in ["health", "nutrition", "population", "hospital"]):
        return "Health"
    if any(k in name_lower for k in ["finance", "banking", "economic", "trade"]):
        return "Finance & Markets"
    if any(k in name_lower for k in ["digital", "computer", "ict", "information"]):
        return "Digital Development"
    if any(k in name_lower for k in ["environment", "forest", "climate", "ecology"]):
        return "Environment"
    if any(k in name_lower for k in ["social", "welfare", "safety net"]):
        return "Social Protection"

    return name.split(",")[0].strip() or "General Procurement"


def fetch_bangladesh_projects(
    use_cache: bool = True,
    cache_path: Path = PROJECTS_CACHE_FILE,
) -> list[ProjectAgencyMap]:
    """Fetch all Bangladesh project metadata from World Bank Projects API or local cache.

    Args:
        use_cache: Whether to use cached JSON from data/raw/ if available.
        cache_path: Path to cache file.

    Returns:
        List of validated ProjectAgencyMap models.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    raw_projects: dict[str, Any] = {}

    if use_cache and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                raw_projects = json.load(f)
        except Exception as e:
            print(f"[Projects API] Cache read error: {e}. Fetching live.")

    if not raw_projects:
        print("[Projects API] Querying World Bank Projects API for Bangladesh (countrycode=BD)...")
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            r = client.get(PROJECTS_API_URL)
            r.raise_for_status()
            data = r.json()
            raw_projects = data.get("projects", {})
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(raw_projects, f, indent=2)
            print(f"[Projects API] Cached {len(raw_projects)} project records to {cache_path}")

    # Supplement with project metadata from contracts raw cache to ensure 100% project coverage
    contracts_raw = _check_local_raw_files()
    for c in contracts_raw:
        pid = str(c.get("projectid") or c.get("project_id") or "").strip()
        pname = str(c.get("project_name") or "").strip()
        if pid and pid not in raw_projects:
            raw_projects[pid] = {"id": pid, "project_name": pname, "impagency": ""}
        elif pid and not raw_projects[pid].get("project_name") and pname:
            raw_projects[pid]["project_name"] = pname

    mappings: list[ProjectAgencyMap] = []
    for pid, p in raw_projects.items():
        if not pid or pid == "total":
            continue
        p_id = str(p.get("id") or pid).strip()
        p_name = str(p.get("project_name") or "Unnamed Project").strip()
        raw_agency = str(p.get("impagency") or "").strip()
        canonical_agency = normalize_agency(raw_agency, project_name=p_name)
        global_practice = extract_global_practice(p)

        try:
            mapping = ProjectAgencyMap(
                project_id=p_id,
                project_name=p_name,
                implementing_agency_raw=raw_agency if raw_agency else "NOT_REPORTED",
                implementing_agency_canonical=canonical_agency,
                global_practice=global_practice,
            )
            mappings.append(mapping)
        except ValidationError as exc:
            pass

    return mappings


def _check_local_raw_files() -> list[dict[str, Any]]:
    """Scan data/raw/ for real offline CSV or JSON dataset files."""
    if CONTRACTS_CACHE_FILE.exists():
        try:
            with open(CONTRACTS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            print(f"[Local Cache] Error reading {CONTRACTS_CACHE_FILE}: {e}")

    # Fallback to individual window files
    window_candidates = [
        DATA_RAW_DIR / "contracts_0037797.json",
        DATA_RAW_DIR / "contracts_0066876.json",
        DATA_RAW_DIR / "contracts_DS00005.json",
        DATA_RAW_DIR / "contracts_0037797.csv",
        DATA_RAW_DIR / "contracts_0066876.csv",
        DATA_RAW_DIR / "contracts_DS00005.csv",
    ]
    seen_ids: set[str] = set()
    all_raw: list[dict[str, Any]] = []

    for path in window_candidates:
        if not path.exists():
            continue
        items: list[dict[str, Any]] = []
        if path.suffix == ".json":
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    items = content if isinstance(content, list) else content.get("contract", [])
            except Exception as e:
                print(f"[Local Fallback] Error reading {path}: {e}")
        elif path.suffix == ".csv":
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    items = list(reader)
            except Exception as e:
                print(f"[Local Fallback] Error reading {path}: {e}")

        for it in items:
            cid = str(it.get("contr_id") or it.get("wb_contract_number") or it.get("borrower_contract_reference_number") or "")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                all_raw.append(it)
            elif not cid:
                all_raw.append(it)

    return all_raw


def fetch_bangladesh_contracts(
    use_cache: bool = True,
    cache_path: Path = CONTRACTS_CACHE_FILE,
    max_records: int | None = None,
) -> tuple[list[RawWBContract], dict[str, int]]:
    """Fetch World Bank Bangladesh contracts across legacy and STEP windows.

    Validates records against RawWBContract (rejecting INDIVIDUAL CONSULTANT placeholders,
    negative USD amounts, and missing supplier_ids).

    Args:
        use_cache: Whether to use cached data in data/raw/.
        cache_path: Main contracts cache JSON path.
        max_records: Optional maximum number of raw records to fetch/process.

    Returns:
        tuple of (valid_contracts, validation_stats_dict)
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    raw_contracts: list[dict[str, Any]] = []

    if use_cache:
        if cache_path != CONTRACTS_CACHE_FILE and cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_contracts = data if isinstance(data, list) else data.get("contract", [])
            except Exception as e:
                print(f"[Contracts Fetcher] Error reading custom cache {cache_path}: {e}")
        else:
            raw_contracts = _check_local_raw_files()
        if raw_contracts:
            print(f"[Contracts Fetcher] Loaded {len(raw_contracts)} records from local raw cache.")

    if not raw_contracts:
        print("[Contracts Fetcher] Querying live World Bank Contracts API for Bangladesh...")
        raw_contracts = _fetch_live_contracts_api(max_records=max_records)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(raw_contracts, f)
        print(f"[Contracts Fetcher] Cached {len(raw_contracts)} contracts to {cache_path}")

    # Parse and validate with Pydantic v2
    valid_contracts: list[RawWBContract] = []
    stats = {
        "total_raw_rows_evaluated": 0,
        "valid_contracts": 0,
        "skipped_placeholder_supplier": 0,
        "skipped_missing_supplier_id": 0,
        "skipped_non_positive_amount": 0,
        "skipped_date_parse_error": 0,
        "skipped_missing_project_or_contract": 0,
        "skipped_other": 0,
    }

    seen_contract_ids: set[str] = set()

    for item in raw_contracts:
        suppinfo = item.get("suppinfo")
        if not suppinfo and item.get("supplier_id") and item.get("supplier"):
            # Support Finances One / DS00005 flat schema
            suppinfo = [
                {
                    "id": item.get("supplier_id"),
                    "name": item.get("supplier"),
                    "countryshortname": item.get("supplier_country") or "Bangladesh",
                    "supplier_contr_amount": item.get("supplier_contract_amount_usd"),
                }
            ]
        elif not suppinfo and item.get("supp_name"):
            suppinfo = [
                {
                    "id": item.get("contr_id") or "UNSPECIFIED",
                    "name": item.get("supp_name")[0] if isinstance(item["supp_name"], list) else item["supp_name"],
                    "countryshortname": "Bangladesh",
                    "supplier_contr_amount": item.get("total_contr_amnt") or item.get("supplier_contr_amount"),
                }
            ]

        if not suppinfo:
            stats["total_raw_rows_evaluated"] += 1
            stats["skipped_missing_supplier_id"] += 1
            continue

        for idx, s in enumerate(suppinfo):
            stats["total_raw_rows_evaluated"] += 1
            base_cid = str(item.get("contr_id") or item.get("wb_contract_number") or item.get("borrower_contract_reference_number") or "").strip()
            if not base_cid:
                stats["skipped_missing_project_or_contract"] += 1
                continue

            supp_id = str(s.get("id") or item.get("supplier_id") or "").strip()
            if not supp_id or supp_id == "UNSPECIFIED":
                stats["skipped_missing_supplier_id"] += 1
                continue

            # Ensure unique contract ID for multi-supplier joint ventures
            cid = base_cid if len(suppinfo) == 1 else f"{base_cid}_S{idx+1}"
            if cid in seen_contract_ids:
                # Disambiguate if same ID appears
                cid = f"{cid}_{supp_id}"
            seen_contract_ids.add(cid)

            # Signing date & strictly derived World Bank fiscal year
            raw_date = item.get("contr_sgn_date") or item.get("contract_signing_date")
            try:
                parsed_d = RawWBContract.parse_signing_date(raw_date)
                fiscal_year = parsed_d.year + 1 if parsed_d.month >= 7 else parsed_d.year
            except Exception:
                year_val = item.get("year") or item.get("fiscal_year") or 2020
                try:
                    fiscal_year = int(str(year_val).split(".")[0])
                except (ValueError, TypeError):
                    fiscal_year = 2020

            # Amount extraction
            amount_val = s.get("supplier_contr_amount") or item.get("supplier_contract_amount_usd") or item.get("total_contr_amnt") or 0.0
            try:
                amount_usd = float(str(amount_val).replace(",", "").strip())
            except (ValueError, TypeError):
                amount_usd = 0.0

            payload = {
                "contract_id": cid,
                "project_id": str(item.get("projectid") or item.get("project_id") or "").strip(),
                "fiscal_year": fiscal_year,
                "review_type": str(item.get("rvw_type") or item.get("review_type") or "Prior").strip(),
                "procurement_category": str(item.get("procurement_group_desc") or item.get("procurement_category") or "OTHER").strip(),
                "procurement_method": str(item.get("procu_meth_text") or item.get("procurement_method") or "Other").strip(),
                "supplier_id": supp_id,
                "supplier_name": str(s.get("name") or item.get("supplier") or "").strip(),
                "supplier_country": str(s.get("countryshortname") or s.get("country") or item.get("supplier_country") or "Bangladesh").strip(),
                "contract_signing_date": item.get("contr_sgn_date") or item.get("contract_signing_date"),
                "supplier_contract_amount_usd": amount_usd,
            }

            try:
                contract = RawWBContract(**payload)
                valid_contracts.append(contract)
                stats["valid_contracts"] += 1
            except ValidationError as exc:
                err_str = str(exc).lower()
                if "placeholder" in err_str:
                    stats["skipped_placeholder_supplier"] += 1
                elif "supplier_id" in err_str:
                    stats["skipped_missing_supplier_id"] += 1
                elif "supplier_contract_amount_usd" in err_str or "greater than 0" in err_str:
                    stats["skipped_non_positive_amount"] += 1
                elif "contract_signing_date" in err_str:
                    stats["skipped_date_parse_error"] += 1
                elif "project_id" in err_str or "contract_id" in err_str:
                    stats["skipped_missing_project_or_contract"] += 1
                else:
                    stats["skipped_other"] += 1

    return valid_contracts, stats


def _fetch_live_contracts_api(max_records: int | None = None) -> list[dict[str, Any]]:
    """Query live World Bank API with pagination."""
    all_contracts: list[dict[str, Any]] = []
    client = httpx.Client(timeout=30.0, follow_redirects=True)
    os = 0
    rows = 500
    total = None

    try:
        while True:
            params = {
                "countryshortname_exact": "Bangladesh",
                "format": "json",
                "rows": rows,
                "os": os,
            }
            r = client.get(CONTRACTS_API_URL, params=params)
            r.raise_for_status()
            data = r.json()
            if total is None:
                total = int(data.get("total", 0))
                print(f"[Contracts Fetcher] Total Bangladesh records reported by API: {total}")

            batch = data.get("contract", [])
            if not batch:
                break
            all_contracts.extend(batch)
            os += len(batch)

            if max_records and len(all_contracts) >= max_records:
                all_contracts = all_contracts[:max_records]
                break

            if os >= total or len(batch) < rows:
                break

            time.sleep(0.05)
    finally:
        client.close()

    return all_contracts


def load_contracts_to_db(
    contracts: list[RawWBContract],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """Insert validated contracts into DuckDB raw_contracts table."""
    con = get_connection(db_path=db_path, read_only=False)
    inserted = 0
    try:
        rows = [
            (
                c.contract_id,
                c.project_id,
                c.fiscal_year,
                c.review_type,
                c.procurement_category,
                c.procurement_method,
                c.supplier_id,
                c.supplier_name,
                c.supplier_country,
                c.contract_signing_date,
                c.supplier_contract_amount_usd,
            )
            for c in contracts
        ]
        con.executemany(
            """
            INSERT OR REPLACE INTO raw_contracts (
                contract_id, project_id, fiscal_year, review_type,
                procurement_category, procurement_method, supplier_id,
                supplier_name, supplier_country, contract_signing_date,
                supplier_contract_amount_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        inserted = len(rows)
    finally:
        con.close()
    return inserted


def load_projects_to_db(
    projects: list[ProjectAgencyMap],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """Insert project-agency mappings into DuckDB mapped_projects table."""
    con = get_connection(db_path=db_path, read_only=False)
    inserted = 0
    try:
        rows = [
            (
                p.project_id,
                p.project_name,
                p.implementing_agency_raw,
                p.implementing_agency_canonical,
                p.global_practice,
            )
            for p in projects
        ]
        con.executemany(
            """
            INSERT OR REPLACE INTO mapped_projects (
                project_id, project_name, implementing_agency_raw,
                implementing_agency_canonical, global_practice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        inserted = len(rows)
    finally:
        con.close()
    return inserted
