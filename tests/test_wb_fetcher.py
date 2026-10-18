"""Unit tests for World Bank fetcher and agency normalization module."""

import json
from pathlib import Path
import pytest

from src.ingestion.wb_fetcher import (
    extract_global_practice,
    fetch_bangladesh_contracts,
    normalize_agency,
)


@pytest.mark.parametrize(
    "raw_agency, expected_canonical",
    [
        ("Local Government Engineering Department", "LGED"),
        ("Local Government Engineering Department (LGED)", "LGED"),
        ("LGED", "LGED"),
        ("Roads and Highways Department", "RHD"),
        ("Roads and Highway Department", "RHD"),
        ("RHD", "RHD"),
        ("Bangladesh Water Development Board", "BWDB"),
        ("Bangladesh Water Development Board (BWDB)", "BWDB"),
        ("BWDB", "BWDB"),
        ("Department of Public Health Engineering", "DPHE"),
        ("Department of Public Health Engineering (DPHE)", "DPHE"),
        ("DPHE", "DPHE"),
        ("Bangladesh Power Development Board", "BPDB"),
        ("BPDB", "BPDB"),
        ("Power Grid Company of Bangladesh", "PGCB"),
        ("Power Grid Company of Bangladesh (PGCB)", "PGCB"),
        ("PGCB", "PGCB"),
        ("Bangladesh Rural Electrification Board", "BREB"),
        ("Chattogram Water Supply and Sewerage Authority (CWASA)", "CWASA"),
        ("Dhaka Water Supply and Sewerage Authority", "DWASA"),
        ("Dhaka North City Corporation (DNCC)", "DNCC"),
        ("Dhaka South City Corporation", "DSCC"),
        ("Bangladesh Forest Department", "BFD"),
        ("Bangladesh Railway", "BR"),
        (None, "UNKNOWN"),
        ("", "UNKNOWN"),
        ("   ", "UNKNOWN"),
    ],
)
def test_normalize_agency(raw_agency, expected_canonical):
    """Verify that implementing agency variants correctly normalize to canonical acronyms."""
    assert normalize_agency(raw_agency) == expected_canonical


def test_extract_global_practice():
    """Verify global practice extraction from project sector metadata."""
    p_transport = {"sector1": {"Name": "Transportation"}}
    assert extract_global_practice(p_transport) == "Transport"

    p_water = {"sector1": {"Name": "Water Supply and Sanitation"}}
    assert extract_global_practice(p_water) == "Water"

    p_energy = {"sector1": {"Name": "Electric Power Transmission and Distribution"}}
    assert extract_global_practice(p_energy) == "Energy"

    p_agri = {"sector1": {"Name": "Agricultural Extension, Research, and Other Support Activities"}}
    assert extract_global_practice(p_agri) == "Agriculture"


def test_fetch_contracts_from_raw_sample(tmp_path: Path):
    """Verify that fetch_bangladesh_contracts reads raw World Bank JSON records and parses valid items."""
    sample_file = tmp_path / "sample_contracts.json"
    raw_data = [
        {
            "contr_id": "1903603",
            "projectid": "P508058",
            "year": "2026",
            "rvw_type": "Post",
            "procurement_group_desc": "Goods",
            "procu_meth_text": "Request for Bids",
            "contr_sgn_date": "08-Oct-2026",
            "suppinfo": [
                {
                    "id": "1134667",
                    "name": "FAABS INTERNATIONAL",
                    "countryshortname": "Bangladesh",
                    "supplier_contr_amount": "46223.84",
                }
            ],
        },
        {
            # Real World Bank placeholder record from SITA project P506691
            "contr_id": "1901304",
            "projectid": "P506691",
            "year": "2026",
            "rvw_type": "Prior",
            "procurement_group_desc": "Consultant Services",
            "procu_meth_text": "Individual Consultant Selection",
            "contr_sgn_date": "20-Sep-2026",
            "suppinfo": [
                {
                    "id": "06422ea1fff5675d",
                    "name": "INDIVIDUAL CONSULTANT",
                    "countryshortname": "Bangladesh",
                    "supplier_contr_amount": "79325.47",
                }
            ],
        },
    ]

    with open(sample_file, "w", encoding="utf-8") as f:
        json.dump(raw_data, f)

    contracts, stats = fetch_bangladesh_contracts(use_cache=True, cache_path=sample_file)
    assert len(contracts) == 1
    assert contracts[0].contract_id == "1903603"
    assert contracts[0].supplier_name == "FAABS INTERNATIONAL"
    assert stats["valid_contracts"] == 1
    assert stats["skipped_placeholder_supplier"] == 1
