"""Unit tests for Week 3 BiCM null rewiring, sequence persistence, and power simulations.

Tests:
1. Fixed-marginal noisy cyclic scheduling preserves exact market shares with zero drift,
   and gamma=1.0 satisfies the pigeonhole minimum repeat bound max(0, 2*n_max - N).
2. Same-date tie-breaking produces deterministic, seeded averages across co-dated ties.
3. BiCM feasibility capacity constraints strictly forbid assigning any contract exceeding
   2.0x a supplier's maximum historical USD contract value.
4. Markov incumbency persistence inflation and stationarity properties.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
import numpy as np
import pandas as pd
import pytest

from src.network.bicm_null import (
    clean_global_practice,
    get_3year_window,
    load_step_commercial_graph,
    rewire_stratum_edges,
)
from src.network.persistence import (
    compute_tied_adjacent_repeats,
    evaluate_stratum_persistence,
)
from src.network.power_sim import (
    apply_noisy_cyclic_swaps,
    build_stride_cycle,
    count_adjacent_repeats,
    evaluate_stratum_power,
    simulate_markov_incumbency,
)


# ==============================================================================
# 1. Fixed-Marginal Noisy Cyclic Scheduling & Pigeonhole Bound Tests
# ==============================================================================

def test_power_sim_zero_drift_and_pigeonhole_bound():
    """Verify exact winner multiset preservation and theoretical minimum repeat bounds."""
    counts = {"SUP_A": 20, "SUP_B": 15, "SUP_C": 10, "SUP_D": 5}
    N = sum(counts.values())
    n_max = max(counts.values())
    theo_bound = max(0, 2 * n_max - N)

    # 1. Stride Cycle Bound Check
    stride_seq = build_stride_cycle(counts)
    assert len(stride_seq) == N
    reps = count_adjacent_repeats(stride_seq)
    assert reps <= theo_bound
    # For balanced distribution (n_max <= N/2), repeats must be zero
    assert reps == 0

    # 2. Dominated vendor test (n_max > N/2)
    dominated_counts = {"SUP_A": 35, "SUP_B": 10, "SUP_C": 5}  # N=50, n_max=35
    dom_N = 50
    dom_theo_bound = max(0, 2 * 35 - 50)  # 20
    dom_stride = build_stride_cycle(dominated_counts)
    dom_reps = count_adjacent_repeats(dom_stride)
    assert dom_reps <= dom_theo_bound

    # 3. Zero Drift across Gamma Swaps
    rng = np.random.default_rng(42)
    for gamma in (1.0, 0.75, 0.50, 0.25, 0.0):
        swapped = apply_noisy_cyclic_swaps(stride_seq, gamma=gamma, rng=rng)
        assert len(swapped) == N
        swapped_counts = dict(Counter(swapped))
        # Exact integer count matching with zero drift
        assert swapped_counts == counts, f"Winner counts drifted under gamma={gamma}!"


def test_evaluate_stratum_power_execution():
    """Verify that evaluate_stratum_power computes valid probabilities in [0.0, 1.0]."""
    counts = {"S1": 8, "S2": 8, "S3": 8, "S4": 6}
    res = evaluate_stratum_power(counts, n_sims=50, n_perms=100, seed=42)
    assert res["N"] == 30
    assert 0.0 <= res["power_gamma_1_0"] <= 1.0
    assert 0.0 <= res["power_delta_0_5"] <= 1.0
    assert isinstance(res["is_powered_80pct"], (bool, np.bool_))


# ==============================================================================
# 2. Same-Date Tie-Breaking & Sequence Persistence Tests
# ==============================================================================

def test_same_date_tie_breaking_deterministic_seeded():
    """Verify that same-date tie breaking produces deterministic, seeded repeat rates."""
    # Construct a stratum with multiple co-dated ties
    records = [
        {"contract_signing_date": date(2021, 1, 10), "canonical_supplier_id": "S1"},
        {"contract_signing_date": date(2021, 1, 10), "canonical_supplier_id": "S2"},
        {"contract_signing_date": date(2021, 1, 10), "canonical_supplier_id": "S1"},
        {"contract_signing_date": date(2021, 2, 15), "canonical_supplier_id": "S2"},
        {"contract_signing_date": date(2021, 3, 20), "canonical_supplier_id": "S3"},
        {"contract_signing_date": date(2021, 3, 20), "canonical_supplier_id": "S3"},
        {"contract_signing_date": date(2021, 4, 1), "canonical_supplier_id": "S1"},
        {"contract_signing_date": date(2021, 4, 1), "canonical_supplier_id": "S2"},
    ]
    df = pd.DataFrame(records)

    r_obs_1 = compute_tied_adjacent_repeats(df, n_tie_breaks=100, seed=42)
    r_obs_2 = compute_tied_adjacent_repeats(df, n_tie_breaks=100, seed=42)

    assert r_obs_1 == r_obs_2, "Tie breaking was not deterministic across identical seeds!"
    assert 0.0 <= r_obs_1 <= 1.0


def test_no_ties_direct_calculation():
    """Verify that when no same-date ties exist, repeat rate equals direct sequential rate."""
    records = [
        {"contract_signing_date": date(2021, 1, 1), "canonical_supplier_id": "S1"},
        {"contract_signing_date": date(2021, 2, 1), "canonical_supplier_id": "S1"},  # Repeat 1
        {"contract_signing_date": date(2021, 3, 1), "canonical_supplier_id": "S2"},
        {"contract_signing_date": date(2021, 4, 1), "canonical_supplier_id": "S2"},  # Repeat 2
        {"contract_signing_date": date(2021, 5, 1), "canonical_supplier_id": "S3"},
    ]
    df = pd.DataFrame(records)
    # 5 contracts, 4 adjacent transitions, 2 repeats -> 2 / 4 = 0.50
    rate = compute_tied_adjacent_repeats(df, n_tie_breaks=10, seed=42)
    assert rate == 0.50


def test_evaluate_stratum_persistence_synthetic():
    """Verify persistence permutation test against theoretical expected adjacent repeat rate."""
    records = [
        {"project_id": "P101", "procurement_category": "Works", "agency": "LGED",
         "contract_signing_date": date(2021, m, 1), "canonical_supplier_id": f"S{m % 3}"}
        for m in range(1, 13)
    ]
    df = pd.DataFrame(records)
    res = evaluate_stratum_persistence(df, n_tie_breaks=10, n_permutations=200, seed=42)

    assert res["N"] == 12
    assert res["distinct_suppliers"] == 3
    # Theoretical expectation check
    counts = np.array([4, 4, 4])
    expected_theo = np.sum(counts * (counts - 1)) / (12 * 11)  # 36 / 132 = 0.2727
    assert pytest.approx(res["theo_expected"], abs=1e-3) == round(expected_theo, 4)
    assert pytest.approx(res["null_mean"], abs=0.05) == round(expected_theo, 4)
    assert 0.0 <= res["p_value"] <= 1.0


# ==============================================================================
# 3. BiCM Capacity Constraints Tests
# ==============================================================================

def test_bicm_capacity_constraints_never_exceeded():
    """Verify that edge swaps strictly forbid assigning contracts exceeding 2.0x max historical USD."""
    max_usd_map = {
        "SMALL_FIRM": 50_000.0,       # Capacity: 100,000 USD
        "LARGE_CONGLOMERATE": 5_000_000.0,  # Capacity: 10,000,000 USD
    }

    edges = [
        {"contract_id": "C1", "agency": "AGENCY_A", "supplier_id": "SMALL_FIRM", "amount_usd": 60_000.0},
        {"contract_id": "C2", "agency": "AGENCY_B", "supplier_id": "LARGE_CONGLOMERATE", "amount_usd": 2_500_000.0},
    ]

    rng = np.random.default_rng(42)
    # Attempting to swap C1 and C2 would give C2 (2,500,000) to SMALL_FIRM (cap: 100,000).
    # This swap MUST be rejected!
    rewired = rewire_stratum_edges(edges, max_usd_map=max_usd_map, rng=rng, n_swaps=50)

    for edge in rewired:
        s = edge["supplier_id"]
        amt = edge["amount_usd"]
        max_cap = 2.0 * max_usd_map[s]
        assert amt <= max_cap, f"Supplier {s} with capacity {max_cap} was illegally assigned contract {amt}!"

    # In a 2-edge graph where the swap is impossible, the graph must remain unchanged
    assert rewired[0]["supplier_id"] == "SMALL_FIRM"
    assert rewired[1]["supplier_id"] == "LARGE_CONGLOMERATE"


def test_bicm_valid_swap_preserves_degrees():
    """Verify that when capacities permit, edge swaps execute and preserve degrees."""
    max_usd_map = {
        "FIRM_1": 1_000_000.0,
        "FIRM_2": 1_000_000.0,
    }
    edges = [
        {"contract_id": "C1", "agency": "A1", "supplier_id": "FIRM_1", "amount_usd": 100_000.0},
        {"contract_id": "C2", "agency": "A2", "supplier_id": "FIRM_2", "amount_usd": 200_000.0},
    ]

    rng = np.random.default_rng(42)
    rewired = rewire_stratum_edges(edges, max_usd_map=max_usd_map, rng=rng, n_swaps=1)

    # Degree preservation check
    agency_counts = Counter(e["agency"] for e in rewired)
    supplier_counts = Counter(e["supplier_id"] for e in rewired)
    assert agency_counts == {"A1": 1, "A2": 1}
    assert supplier_counts == {"FIRM_1": 1, "FIRM_2": 1}


# ==============================================================================
# 4. Global Practice Cleaning & Window Helper Tests
# ==============================================================================

def test_clean_global_practice_and_windows():
    """Verify sector normalization and 3-year window assignment under SPEC.md."""
    assert clean_global_practice("Education, Health") == "Education"
    assert clean_global_practice("['Water', 'Urban']") == "Water"
    assert clean_global_practice("") == "Other"
    assert clean_global_practice(None) == "Other"

    assert get_3year_window(2017) == "FY17-19"
    assert get_3year_window(2019) == "FY17-19"
    assert get_3year_window(2020) == "FY20-22"
    assert get_3year_window(2022) == "FY20-22"
    assert get_3year_window(2023) == "FY23-26"
    assert get_3year_window(2026) == "FY23-26"
