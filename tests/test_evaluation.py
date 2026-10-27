"""Unit and integration tests for Week 4 evaluation models, sensitivity grid, and calibrated power.

Tests:
1. Natural cubic spline feature engineering (patsy centered constraints, df=4).
2. Within-agency descriptive OLS models (HC3 robust and agency-clustered standard errors).
3. World Bank debarred firms cross-check matching logic and precision.
4. Jaccard@K dyad overlap calculation across sensitivity thresholds.
5. Calibrated discrete permutation power boundaries for sparse vs. dense strata.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.evaluation.regime_models import (
    build_spline_features,
    cross_check_debarred_firms,
    fit_within_agency_ols,
)
from src.evaluation.sensitivity import compute_jaccard_similarity
from src.network.power_sim import evaluate_stratum_power


# ==============================================================================
# 1. Natural Cubic Splines Feature Engineering Tests
# ==============================================================================

def test_spline_features_shape_and_orthogonality():
    """Verify natural cubic splines generate exactly df=4 columns without collinearity."""
    np.random.seed(42)
    df = pd.DataFrame({
        "log_usd": np.random.uniform(8.0, 16.0, size=150),
    })

    df_out, spline_cols = build_spline_features(df, var_name="log_usd", df_spline=4)

    assert len(spline_cols) == 4
    assert spline_cols == ["spline_0", "spline_1", "spline_2", "spline_3"]
    assert all(col in df_out.columns for col in spline_cols)
    assert not df_out[spline_cols].isna().any().any()
    assert np.all(np.isfinite(df_out[spline_cols].values))

    # Check rank of spline matrix (must be full rank 4)
    rank = np.linalg.matrix_rank(df_out[spline_cols].values)
    assert rank == 4


# ==============================================================================
# 2. Within-Agency OLS Regression Tests
# ==============================================================================

def test_within_agency_ols_execution():
    """Verify within-agency OLS regression fits with both HC3 and clustered SEs."""
    np.random.seed(42)
    n = 200
    df = pd.DataFrame({
        "dyad_bicm_z_score": np.random.normal(0, 1, size=n),
        "agency_supplier_share": np.random.uniform(0.01, 0.40, size=n),
        "is_post_review": np.random.binomial(1, 0.80, size=n),
        "agency": np.random.choice(["AGENCY_A", "AGENCY_B", "AGENCY_C", "AGENCY_D"], size=n),
        "procurement_category": np.random.choice(["Works", "Goods", "Consultant Services"], size=n),
        "procurement_method": np.random.choice(["RFB", "RFQ", "Direct Selection"], size=n),
        "log_usd": np.random.uniform(9.0, 15.0, size=n),
    })

    df_featured, spline_cols = build_spline_features(df, var_name="log_usd", df_spline=4)

    res_m1 = fit_within_agency_ols(df_featured, dep_var="dyad_bicm_z_score", spline_cols=spline_cols)
    assert res_m1["n_obs"] == n
    assert res_m1["n_agencies"] == 4
    assert np.isfinite(res_m1["coef_post_review"])
    assert res_m1["se_hc3"] > 0
    assert res_m1["se_clustered"] > 0
    assert 0.0 <= res_m1["p_value_hc3"] <= 1.0
    assert 0.0 <= res_m1["p_value_clustered"] <= 1.0
    assert res_m1["ci_95_hc3"][0] < res_m1["ci_95_hc3"][1]
    assert res_m1["ci_95_clustered"][0] < res_m1["ci_95_clustered"][1]

    res_m2 = fit_within_agency_ols(df_featured, dep_var="agency_supplier_share", spline_cols=spline_cols)
    assert res_m2["n_obs"] == n
    assert np.isfinite(res_m2["coef_post_review"])


# ==============================================================================
# 3. Debarred Firms Sanity Cross-Check Tests
# ==============================================================================

def test_cross_check_debarred_firms():
    """Verify debarred firms cross-check detects known sanctioned firms and ignores non-matches."""
    suppliers_df = pd.DataFrame([
        {"canonical_supplier_id": "CAN_SUP_001", "canonical_name": "TIGER IT BANGLADESH LTD"},
        {"canonical_supplier_id": "CAN_SUP_002", "canonical_name": "SMEC INTERNATIONAL PTY LIMITED"},
        {"canonical_supplier_id": "CAN_SUP_003", "canonical_name": "MIR AKHTER HOSSAIN LTD"},
        {"canonical_supplier_id": "CAN_SUP_004", "canonical_name": "STANDARD COMPLIANT BANGLADESH CONTRACTOR"},
    ])

    test_debarred_list = [
        {"firm_name": "TIGER IT BANGLADESH LTD", "grounds": "Collusion", "status": "Debarred"},
        {"firm_name": "SMEC INTERNATIONAL PTY LTD", "grounds": "Corruption", "status": "Debarred"},
        {"firm_name": "MIR AKHTER HOSSAIN LTD", "grounds": "Sanctioned", "status": "Sanctioned"},
        {"firm_name": "UNRELATED DEFICIT FIRM", "grounds": "Fraud", "status": "Debarred"},
    ]

    matches = cross_check_debarred_firms(suppliers_df, debarred_source=test_debarred_list, threshold=85.0)

    matched_ids = set(matches["canonical_supplier_id"])
    assert "CAN_SUP_001" in matched_ids
    assert "CAN_SUP_002" in matched_ids
    assert "CAN_SUP_003" in matched_ids
    assert "CAN_SUP_004" not in matched_ids
    assert len(matches) == 3


# ==============================================================================
# 4. Sensitivity Jaccard@K Overlap Tests
# ==============================================================================

def test_jaccard_similarity_calculation():
    """Verify Jaccard index computation across identical, disjoint, and partial sets."""
    # Empty sets
    assert compute_jaccard_similarity(set(), set()) == 1.0

    # Identical sets
    set_a = {("LGED", "SUP_A"), ("DPHE", "SUP_B"), ("RHD", "SUP_C")}
    assert compute_jaccard_similarity(set_a, set_a) == 1.0

    # Disjoint sets
    set_b = {("BWDB", "SUP_D"), ("DLS", "SUP_E")}
    assert compute_jaccard_similarity(set_a, set_b) == 0.0

    # Partial overlap: 2 shared, 2 in A only, 1 in C only -> union 5, intersection 2 -> 0.40
    set_c = {("LGED", "SUP_A"), ("DPHE", "SUP_B"), ("BWDB", "SUP_F")}
    assert pytest.approx(compute_jaccard_similarity(set_a, set_c), 0.01) == 2.0 / 4.0  # union is 4 items


# ==============================================================================
# 5. Discrete Permutation Power Boundary Tests
# ==============================================================================

def test_calibrated_discrete_permutation_power_bounds():
    """Verify mathematical calibration fix: sparse strata have 0% power for rotation at alpha=0.05.

    When N=10 and n_max=2 (P(R = R_max) = 2/10 = 0.20 > 0.05), discrete mass prevents
    rejection of the null at alpha = 0.05 under anti-persistent rotation.
    """
    sparse_counts = {
        "S1": 2, "S2": 1, "S3": 1, "S4": 1, "S5": 1, 
        "S6": 1, "S7": 1, "S8": 1, "S9": 1
    }
    res_sparse = evaluate_stratum_power(sparse_counts, n_sims=50, n_perms=100, seed=42)
    assert res_sparse["N"] == 10
    # In sparse strata, discrete mass ensures rotation power is 0.0
    assert res_sparse["power_rotation_gamma_100"] == 0.0
    assert res_sparse["power_rotation_gamma_075"] == 0.0
    assert not res_sparse["is_powered_rotation_80pct"]

    # In a dense stratum with large N and high vendor repeats, incumbency power is high
    dense_counts = {"S1": 25, "S2": 25, "S3": 25, "S4": 25}
    res_dense = evaluate_stratum_power(dense_counts, n_sims=50, n_perms=100, seed=42)
    assert res_dense["N"] == 100
    assert res_dense["power_incumbency_delta_050"] >= 0.80
    assert res_dense["is_powered_incumbency_80pct"]
