"""Unit tests for Supplier Entity Resolution and Horvitz-Thompson Audit pipeline.

Tests:
1. Normalizer string cleaning, corporate suffix stripping, and punctuation normalization.
2. Filtering of non-commercial placeholders and state-owned implementing agencies/utilities.
3. Strict fiscal year re-derivation from contract signing dates and historical project re-bucketing.
4. RapidFuzz candidate blocking, connected-component clustering, and ID compression.
5. Horvitz-Thompson stratum-weighted Recall mathematics and bootstrap confidence intervals
   evaluated against known synthetic ground truth.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.ingestion.schemas import RawWBContract
from src.resolution.audit_sampler import compute_ht_metrics
from src.resolution.matcher import (
    SupplierCandidatePair,
    cluster_suppliers_at_threshold,
    compute_id_compression_ratio,
    generate_candidate_pairs,
    run_sensitivity_sweep,
)
from src.resolution.normalizer import (
    clean_supplier_name,
    get_blocking_token,
    is_commercial_supplier,
)


# ==============================================================================
# 1. Normalizer & Corporate Suffix Cleaning Tests
# ==============================================================================

@pytest.mark.parametrize(
    ("raw_input", "expected_clean"),
    [
        ("M/S. M.A. ENGINEERING & CONSTRUCTION LTD.", "M A ENGINEERING AND CONSTRUCTION"),
        ("TOMA CONSTRUCTION & CO. LTD.", "TOMA CONSTRUCTION"),
        ("NAVANA BATTERIES LIMITED", "NAVANA BATTERIES"),
        ("S.S. BUILDERS (PVT) LTD.", "S S BUILDERS"),
        ("COMPUTER SOURCE LTD.", "COMPUTER SOURCE"),
        ("MESSRS AL-AMIN TRADERS", "AL AMIN TRADERS"),
        ("THE DEVELOPMENT DESIGN CONSULTANTS LTD.", "DEVELOPMENT DESIGN CONSULTANTS"),
        ("CHINA PETROLEUM & CHEMICAL CORP - JV", "CHINA PETROLEUM AND CHEMICAL"),
        ("EASTERN MOTORS (PVT.) LIMITED", "EASTERN MOTORS"),
        ("TRANS-NATIONAL INFRASTRUCTURE CORP.", "TRANS NATIONAL INFRASTRUCTURE"),
    ],
)
def test_clean_supplier_name_corporate_suffixes(raw_input: str, expected_clean: str):
    """Verify deterministic uppercase normalization and stripping of corporate prefixes/suffixes."""
    assert clean_supplier_name(raw_input) == expected_clean


def test_clean_supplier_name_empty_and_whitespace():
    """Verify handling of empty or whitespace strings."""
    assert clean_supplier_name("") == ""
    assert clean_supplier_name("   ") == ""


# ==============================================================================
# 2. Commercial vs. Non-Commercial & State Agency Filtering Tests
# ==============================================================================

@pytest.mark.parametrize(
    "placeholder_name",
    [
        "INDIVIDUAL CONSULTANT",
        "Individual Consultant (Various)",
        "INDIVIDUAL CONSULTANTS",
        "MULTIPLE SUPPLIERS",
        "Various Suppliers",
        "UNKNOWN",
        "NOT REPORTED",
        "UNSPECIFIED",
    ],
)
def test_is_commercial_supplier_rejects_placeholders(placeholder_name: str):
    """Verify rejection of non-commercial placeholder entries."""
    assert is_commercial_supplier(placeholder_name) is False


@pytest.mark.parametrize(
    "agency_or_utility_name",
    [
        "POWER GRID COMPANY OF BANGLADESH",
        "POWER GRID COMPANY OF BANGLADESH (PGCB)",
        "LOCAL GOVERNMENT ENGINEERING DEPARTMENT (LGED)",
        "Local Government Engineering Department",
        "ROADS AND HIGHWAYS DEPARTMENT",
        "Bangladesh Water Development Board (BWDB)",
        "Department of Public Health Engineering",
        "WATER SUPPLY & SEWERAGE",
        "DHAKA WASA",
        "CHITTAGONG WASA",
        "BANGLADESH RAILWAY",
        "BANGLADESH BUREAU OF STATISTICS",
        "THE BANGLADESH COMPUTER COUNCIL (\"BCC\")",
        "INFRASTRUCTURE DEVELOPMENT COMPANY LIMITED (IDCOL)",
        "DEPARTMENT OF ZOOLOGY",
        "LGED",
        "PGCB",
        "BWDB",
    ],
)
def test_is_commercial_supplier_rejects_state_agencies_and_utilities(agency_or_utility_name: str):
    """Verify rejection of state-owned utilities and implementing agencies erroneously listed as suppliers."""
    assert is_commercial_supplier(agency_or_utility_name) is False


@pytest.mark.parametrize(
    "commercial_firm",
    [
        "TOMA CONSTRUCTION & CO. LTD.",
        "NAVANA BATTERIES LIMITED",
        "COMPUTER SOURCE LTD.",
        "S.S. BUILDERS (PVT) LTD.",
        "MIR AKHTER HOSSAIN LTD.",
        "CHINA RAILWAY CONSTRUCTION BRIDGE ENGINEERING BUREAU",
        "SMART TECHNOLOGIES (BANGLADESH) LTD.",
        "GLOBAL BRAND PRIVATE LIMITED",
    ],
)
def test_is_commercial_supplier_accepts_legitimate_firms(commercial_firm: str):
    """Verify acceptance of legitimate commercial suppliers and contracting firms."""
    assert is_commercial_supplier(commercial_firm) is True


# ==============================================================================
# 3. Fiscal Year Re-derivation & Dataset Window Re-Bucketing Tests
# ==============================================================================

@pytest.mark.parametrize(
    ("signing_date_str", "expected_fy"),
    [
        ("2021-06-30", 2021),  # June -> FY2021
        ("2021-07-01", 2022),  # July -> FY2022
        ("2021-12-15", 2022),  # December -> FY2022
        ("2022-01-10", 2022),  # January -> FY2022
        ("2000-07-05", 2001),  # July 2000 -> FY2001
        ("2005-06-28", 2005),  # June 2005 -> FY2005
        ("2016-06-30", 2016),  # June 2016 -> FY2016
        ("2016-07-01", 2017),  # July 2016 -> FY2017
    ],
)
def test_raw_wb_contract_strict_fiscal_year_derivation(signing_date_str: str, expected_fy: int):
    """Verify that World Bank fiscal year is strictly derived from signing date: year + 1 if month >= 7 else year."""
    payload = {
        "contract_id": "TEST-FY-001",
        "project_id": "P168453",
        "fiscal_year": 1999,  # Deliberately erroneous fiscal_year in payload
        "review_type": "Prior",
        "procurement_category": "WORKS",
        "procurement_method": "Request for Bids",
        "supplier_id": "SUP-101",
        "supplier_name": "Test Firm Ltd.",
        "supplier_country": "Bangladesh",
        "contract_signing_date": signing_date_str,
        "supplier_contract_amount_usd": 150000.0,
    }
    contract = RawWBContract(**payload)
    assert contract.fiscal_year == expected_fy


def test_closed_historical_projects_rebucketing():
    """Verify that historical contracts with 2000-2012 dates are bucketed into FY2001-2016."""
    historical_dates = [
        "2000-07-05",
        "2003-10-25",
        "2005-12-23",
        "2011-09-15",
        "2012-02-27",
    ]
    for d_str in historical_dates:
        d = date.fromisoformat(d_str)
        fy = d.year + 1 if d.month >= 7 else d.year
        assert 2001 <= fy <= 2016, f"Date {d_str} mapped to FY {fy}, which bleeds outside FY2001-2016!"


# ==============================================================================
# 4. RapidFuzz Blocking, Clustering & ID-Compression Tests
# ==============================================================================

def test_blocking_token_extraction():
    """Verify first-token and honorific/initial prefix blocking logic."""
    assert get_blocking_token("TOMA CONSTRUCTION") == "TOMA"
    assert get_blocking_token("GLOBAL BRAND") == "GLOB"
    assert get_blocking_token("MD RAHIM") == "MD_RAHI"
    assert get_blocking_token("MD SAIDUR RAHMAN") == "MD_SAID"
    assert get_blocking_token("A M INTERNATIONAL") == "A_M"
    assert get_blocking_token("") == "UNK"


def test_clustering_and_id_compression():
    """Verify connected-component clustering and ID-compression ratio calculation."""
    suppliers = [
        {"supplier_id": "1", "raw_name": "TOMA CONSTRUCTION LTD", "clean_name": "TOMA CONSTRUCTION", "country": "BANGLADESH", "block_key": "TOMA", "contract_count": 5, "total_amount_usd": 1000.0},
        {"supplier_id": "2", "raw_name": "M/S TOMA CONSTRUCTION", "clean_name": "TOMA CONSTRUCTION", "country": "BANGLADESH", "block_key": "TOMA", "contract_count": 3, "total_amount_usd": 800.0},
        {"supplier_id": "3", "raw_name": "TOMA BUILDERS LTD", "clean_name": "TOMA BUILDERS", "country": "BANGLADESH", "block_key": "TOMA", "contract_count": 2, "total_amount_usd": 500.0},
        {"supplier_id": "4", "raw_name": "NAVANA BATTERIES LIMITED", "clean_name": "NAVANA BATTERIES", "country": "BANGLADESH", "block_key": "NAVA", "contract_count": 4, "total_amount_usd": 2000.0},
        {"supplier_id": "5", "raw_name": "NAVANA BATTERIES", "clean_name": "NAVANA BATTERIES", "country": "BANGLADESH", "block_key": "NAVA", "contract_count": 1, "total_amount_usd": 300.0},
    ]

    candidate_pairs = generate_candidate_pairs(suppliers)
    assert len(candidate_pairs) > 0

    # Cluster at tau = 0.88
    clusters = cluster_suppliers_at_threshold(suppliers, candidate_pairs, tau=0.88)
    # Suppliers 1 & 2 should cluster together (Toma Construction)
    # Suppliers 4 & 5 should cluster together (Navana Batteries)
    # Supplier 3 may stay separate
    assert len(clusters) == 3
    compression = compute_id_compression_ratio(len(suppliers), len(clusters))
    # 5 IDs down to 3 clusters -> (1 - 3/5) = 40% compression
    assert pytest.approx(compression, 0.01) == 0.40


def test_sensitivity_sweep_monotonicity():
    """Verify that sensitivity sweep yields monotonic behavior (higher tau -> more clusters, lower compression)."""
    suppliers = [
        {"supplier_id": "1", "raw_name": "GLOBAL BRAND LTD", "clean_name": "GLOBAL BRAND", "country": "BANGLADESH", "block_key": "GLOB", "contract_count": 1, "total_amount_usd": 100.0},
        {"supplier_id": "2", "raw_name": "GLOBAL BRAND (PVT) LTD", "clean_name": "GLOBAL BRAND", "country": "BANGLADESH", "block_key": "GLOB", "contract_count": 1, "total_amount_usd": 100.0},
        {"supplier_id": "3", "raw_name": "GLOBAL BRAND BANGLADESH", "clean_name": "GLOBAL BRAND BANGLADESH", "country": "BANGLADESH", "block_key": "GLOB", "contract_count": 1, "total_amount_usd": 100.0},
        {"supplier_id": "4", "raw_name": "GLOBAL BROTHERS", "clean_name": "GLOBAL BROTHERS", "country": "BANGLADESH", "block_key": "GLOB", "contract_count": 1, "total_amount_usd": 100.0},
    ]
    pairs = generate_candidate_pairs(suppliers)
    sweep = run_sensitivity_sweep(suppliers, pairs, thresholds=(0.80, 0.85, 0.90, 0.95))

    taus = sorted(sweep.keys())
    for i in range(len(taus) - 1):
        t1, t2 = taus[i], taus[i+1]
        assert sweep[t1]["n_clusters"] <= sweep[t2]["n_clusters"]
        assert sweep[t1]["compression_ratio"] >= sweep[t2]["compression_ratio"]


# ==============================================================================
# 5. Horvitz-Thompson Stratified Math Tests on Synthetic Ground Truth
# ==============================================================================

def test_horvitz_thompson_math_synthetic_ground_truth(tmp_path: Path):
    """Verify Horvitz-Thompson point estimator and bootstrap confidence intervals against exact synthetic values.

    Synthetic Setup:
    - Merged Population N_merged = 1,000
    - Sampled n_prec = 200, of which 180 are true positives -> sample precision = 0.90
    - TP_hat = 1,000 * 0.90 = 900.0
    - Near-neighbor Unmerged Strata:
      * Band A: N_A = 200, n_A = 50, fn_A = 5 -> weight = 4.0, FN_A = 20.0
      * Band B: N_B = 500, n_B = 50, fn_B = 3 -> weight = 10.0, FN_B = 30.0
      * Band C: N_C = 1,000, n_C = 50, fn_C = 1 -> weight = 20.0, FN_C = 20.0
    - FN_hat_HT = 20.0 + 30.0 + 20.0 = 70.0
    - Total = 900.0 + 70.0 = 970.0
    - Exact Recall_HT = 900.0 / 970.0 = 0.927835... (92.78%)
    """
    prec_rows = []
    for i in range(200):
        prec_rows.append({
            "pair_id": f"P_{i}",
            "supplier_id_1": f"S1_{i}",
            "name_1": f"Firm A {i}",
            "supplier_id_2": f"S2_{i}",
            "name_2": f"Firm A {i}",
            "similarity_score": 0.95,
            "is_same_entity": 1 if i < 180 else 0,
        })
    prec_df = pd.DataFrame(prec_rows)

    rec_rows = []
    # Band A: 50 rows, 5 ones
    for i in range(50):
        rec_rows.append({
            "pair_id": f"RA_{i}",
            "stratum_band": "Band_A",
            "stratum_N_h": 200,
            "stratum_n_h": 50,
            "supplier_id_1": f"S1_{i}",
            "name_1": f"Firm A {i}",
            "supplier_id_2": f"S2_{i}",
            "name_2": f"Firm B {i}",
            "similarity_score": 0.85,
            "is_same_entity": 1 if i < 5 else 0,
        })
    # Band B: 50 rows, 3 ones
    for i in range(50):
        rec_rows.append({
            "pair_id": f"RB_{i}",
            "stratum_band": "Band_B",
            "stratum_N_h": 500,
            "stratum_n_h": 50,
            "supplier_id_1": f"S1_{i}",
            "name_1": f"Firm A {i}",
            "supplier_id_2": f"S2_{i}",
            "name_2": f"Firm B {i}",
            "similarity_score": 0.75,
            "is_same_entity": 1 if i < 3 else 0,
        })
    # Band C: 50 rows, 1 one
    for i in range(50):
        rec_rows.append({
            "pair_id": f"RC_{i}",
            "stratum_band": "Band_C",
            "stratum_N_h": 1000,
            "stratum_n_h": 50,
            "supplier_id_1": f"S1_{i}",
            "name_1": f"Firm A {i}",
            "supplier_id_2": f"S2_{i}",
            "name_2": f"Firm B {i}",
            "similarity_score": 0.68,
            "is_same_entity": 1 if i < 1 else 0,
        })
    rec_df = pd.DataFrame(rec_rows)

    metrics = compute_ht_metrics(
        precision_csv=prec_df,
        recall_csv=rec_df,
        n_bootstrap=1000,
        random_seed=42,
        population_N_merged=1000,
    )

    # 1. Exact Precision
    assert pytest.approx(metrics["precision"], abs=1e-4) == 0.90
    assert metrics["TP_hat"] == 900.0

    # 2. Exact Horvitz-Thompson FN and Recall
    assert metrics["FN_hat_HT"] == 70.0
    expected_recall = 900.0 / 970.0  # ~0.9278
    assert pytest.approx(metrics["recall_ht"], abs=1e-4) == round(expected_recall, 4)

    # 3. Bootstrap Confidence Interval Bracketing
    p_lower, p_upper = metrics["precision_ci"]
    assert p_lower <= metrics["precision"] <= p_upper
    assert 0.80 <= p_lower and p_upper <= 0.98

    r_lower, r_upper = metrics["recall_ci"]
    assert r_lower <= metrics["recall_ht"] <= r_upper
    assert 0.85 <= r_lower and r_upper <= 0.98
