"""Bipartite Configuration Model (BiCM) null rewiring engine.

Evaluates agency-supplier dyad concentration and agency-level Herfindahl-Hirschman
Index (HHI) / Top-3 Supplier Share z-scores on the FY2017-2026 STEP commercial
bipartite graph, with degree-preserving edge swaps strictly stratified within
(procurement_category, global_practice, window_3yr) and capacity-constrained by
2.0x maximum observed historical contract USD values.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from src.ingestion.db import DEFAULT_DB_PATH, get_connection
from src.resolution.normalizer import is_commercial_supplier


def clean_global_practice(raw_gp: Any) -> str:
    """Normalize raw global practice string into a concise sector label."""
    if not raw_gp:
        return "Other"
    val = str(raw_gp).strip()
    # Handle list-like or JSON-like strings
    val = val.replace("[", "").replace("]", "").replace("'", "").replace('"', "").strip()
    if not val or val.startswith("{"):
        return "Other"
    first_part = val.split(",")[0].strip()
    return first_part if first_part else "Other"


def get_3year_window(fiscal_year: int) -> str:
    """Map fiscal year to explicit 3-year window buckets under SPEC.md Section 3."""
    if fiscal_year <= 2019:
        return "FY17-19"
    elif fiscal_year <= 2022:
        return "FY20-22"
    else:
        return "FY23-26"


def load_step_commercial_graph(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Load the FY2017-2026 STEP commercial contract bipartite graph and supplier capacities.

    Args:
        db_path: Path to DuckDB database.

    Returns:
        tuple: (df_contracts, max_historical_usd_dict)
    """
    con = get_connection(db_path=db_path, read_only=True)
    try:
        # 1. Historical max contract USD across all years for capacity constraints
        max_usd_query = """
            WITH supplier_lookup AS (
                SELECT 
                    canonical_supplier_id,
                    UNNEST(raw_supplier_ids) as raw_supplier_id
                FROM canonical_suppliers
            )
            SELECT 
                sl.canonical_supplier_id,
                MAX(rc.supplier_contract_amount_usd) as max_usd
            FROM raw_contracts rc
            INNER JOIN supplier_lookup sl ON rc.supplier_id = sl.raw_supplier_id
            GROUP BY sl.canonical_supplier_id
        """
        max_usd_map = dict(con.execute(max_usd_query).fetchall())

        # 2. STEP contracts (FY2017-2026) joined to canonical suppliers and agency metadata
        contracts_query = """
            WITH supplier_lookup AS (
                SELECT 
                    canonical_supplier_id,
                    canonical_name,
                    UNNEST(raw_supplier_ids) as raw_supplier_id
                FROM canonical_suppliers
            )
            SELECT 
                rc.contract_id,
                rc.project_id,
                COALESCE(mp.implementing_agency_canonical, 'UNKNOWN') as agency,
                sl.canonical_supplier_id as supplier_id,
                sl.canonical_name as supplier_name,
                rc.supplier_name as raw_supplier_name,
                rc.supplier_contract_amount_usd as amount_usd,
                rc.procurement_category,
                COALESCE(mp.global_practice, 'Other') as global_practice,
                rc.fiscal_year,
                rc.contract_signing_date
            FROM raw_contracts rc
            INNER JOIN supplier_lookup sl ON rc.supplier_id = sl.raw_supplier_id
            LEFT JOIN mapped_projects mp ON rc.project_id = mp.project_id
            WHERE rc.fiscal_year >= 2017
            ORDER BY rc.contract_signing_date ASC
        """
        raw_df = con.execute(contracts_query).df()
    finally:
        con.close()

    # Filter out any non-commercial / state-agency records
    valid_rows = []
    for _, row in raw_df.iterrows():
        raw_name = str(row["raw_supplier_name"])
        if is_commercial_supplier(raw_name):
            valid_rows.append(row)

    df = pd.DataFrame(valid_rows)
    df["global_practice_clean"] = df["global_practice"].apply(clean_global_practice)
    df["window_3yr"] = df["fiscal_year"].apply(get_3year_window)

    return df, max_usd_map


def rewire_stratum_edges(
    edges: list[dict[str, Any]],
    max_usd_map: dict[str, float],
    rng: np.random.Generator,
    n_swaps: int,
) -> list[dict[str, Any]]:
    """Execute degree-preserving, capacity-constrained edge swaps within a single stratum.

    Swaps two edges:
        (A1, S1) with amount V1, and (A2, S2) with amount V2
    into:
        (A1, S2) with amount V1, and (A2, S1) with amount V2
    subject to:
        V1 <= 2.0 * max_usd[S2] and V2 <= 2.0 * max_usd[S1].

    Args:
        edges: List of contract edge dictionaries within the stratum.
        max_usd_map: Maximum historical contract amount per supplier.
        rng: Deterministic numpy random generator.
        n_swaps: Target number of valid edge swaps to execute.

    Returns:
        List of rewired contract edge dictionaries.
    """
    E = len(edges)
    if E < 2:
        return edges

    agencies = [e["agency"] for e in edges]
    suppliers = [e["supplier_id"] for e in edges]
    amounts = np.array([e["amount_usd"] for e in edges], dtype=float)
    contract_ids = [e["contract_id"] for e in edges]

    # Pre-lookup capacity: 2.0 * max_historical_usd
    capacities = np.array([2.0 * max_usd_map.get(s, amounts[idx]) for idx, s in enumerate(suppliers)], dtype=float)

    successful_swaps = 0
    attempts = 0
    max_attempts = max(n_swaps * 10, 100)

    while successful_swaps < n_swaps and attempts < max_attempts:
        attempts += 1
        i = rng.integers(0, E)
        j = rng.integers(0, E)
        if i == j:
            continue

        a1, a2 = agencies[i], agencies[j]
        s1, s2 = suppliers[i], suppliers[j]

        # In bipartite multigraph, degree is preserved when swapping distinct agencies or suppliers
        if a1 == a2 or s1 == s2:
            continue

        v1 = amounts[i]
        v2 = amounts[j]

        # Feasibility capacity check
        cap2 = capacities[j]  # supplier S2 capacity
        cap1 = capacities[i]  # supplier S1 capacity

        if v1 <= cap2 and v2 <= cap1:
            suppliers[i], suppliers[j] = s2, s1
            capacities[i], capacities[j] = cap2, cap1
            successful_swaps += 1

    return [
        {
            "contract_id": contract_ids[k],
            "agency": agencies[k],
            "supplier_id": suppliers[k],
            "amount_usd": amounts[k],
        }
        for k in range(E)
    ]


def run_bicm_null_simulation(
    df_contracts: pd.DataFrame,
    max_usd_map: dict[str, float],
    n_rewirings: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Execute 1,000 BiCM null rewirings across strata and compute concentration statistics.

    Args:
        df_contracts: DataFrame of STEP commercial contracts.
        max_usd_map: Supplier capacity mapping.
        n_rewirings: Number of null graph configurations (default 1,000).
        seed: Deterministic numpy random seed.

    Returns:
        dict containing:
            - 'dyad_results': DataFrame of agency-supplier dyad z-scores and empirical p-values.
            - 'agency_results': DataFrame of agency HHI and Top-3 share z-scores.
            - 'summary': High-level simulation metadata.
    """
    rng = np.random.default_rng(seed)

    # 1. Group contracts by stratum
    strata: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for _, row in df_contracts.iterrows():
        key = (
            str(row["procurement_category"]),
            str(row["global_practice_clean"]),
            str(row["window_3yr"]),
        )
        strata[key].append({
            "contract_id": row["contract_id"],
            "agency": row["agency"],
            "supplier_id": row["supplier_id"],
            "amount_usd": float(row["amount_usd"]),
        })

    # Supplier name lookup
    supplier_names = dict(zip(df_contracts["supplier_id"], df_contracts["supplier_name"]))

    # 2. Observed Dyad and Agency statistics
    obs_dyad_counts: dict[tuple[str, str], int] = defaultdict(int)
    obs_dyad_usd: dict[tuple[str, str], float] = defaultdict(float)
    obs_agency_volumes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for _, row in df_contracts.iterrows():
        a = row["agency"]
        s = row["supplier_id"]
        v = float(row["amount_usd"])
        obs_dyad_counts[(a, s)] += 1
        obs_dyad_usd[(a, s)] += v
        obs_agency_volumes[a][s] += v

    obs_agency_hhi: dict[str, float] = {}
    obs_agency_cr3: dict[str, float] = {}
    agency_totals: dict[str, tuple[int, float]] = {}

    for a, s_dict in obs_agency_volumes.items():
        tot_vol = sum(s_dict.values())
        tot_cnt = sum(obs_dyad_counts[(a, s)] for s in s_dict)
        agency_totals[a] = (tot_cnt, tot_vol)

        if tot_vol > 0:
            shares = np.array(list(s_dict.values())) / tot_vol
            obs_agency_hhi[a] = float(np.sum(shares ** 2))
            sorted_shares = np.sort(shares)[::-1]
            obs_agency_cr3[a] = float(np.sum(sorted_shares[:3]))
        else:
            obs_agency_hhi[a] = 0.0
            obs_agency_cr3[a] = 0.0

    # 3. Simulate Null Graphs
    observed_dyad_keys = list(obs_dyad_counts.keys())
    observed_agencies = list(obs_agency_volumes.keys())

    null_dyad_counts = {k: np.empty(n_rewirings, dtype=float) for k in observed_dyad_keys}
    null_dyad_usd = {k: np.empty(n_rewirings, dtype=float) for k in observed_dyad_keys}

    null_agency_hhi = {a: np.empty(n_rewirings, dtype=float) for a in observed_agencies}
    null_agency_cr3 = {a: np.empty(n_rewirings, dtype=float) for a in observed_agencies}

    for b in range(n_rewirings):
        b_dyad_cnt: dict[tuple[str, str], int] = defaultdict(int)
        b_dyad_val: dict[tuple[str, str], float] = defaultdict(float)
        b_agency_vols: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for stratum_key, edge_list in strata.items():
            n_edges = len(edge_list)
            if n_edges >= 2:
                # 2x swaps for thorough mixing
                swapped = rewire_stratum_edges(
                    edges=edge_list,
                    max_usd_map=max_usd_map,
                    rng=rng,
                    n_swaps=n_edges * 2,
                )
            else:
                swapped = edge_list

            for edge in swapped:
                a = edge["agency"]
                s = edge["supplier_id"]
                v = edge["amount_usd"]
                b_dyad_cnt[(a, s)] += 1
                b_dyad_val[(a, s)] += v
                b_agency_vols[a][s] += v

        # Record for observed dyads
        for dyad_key in observed_dyad_keys:
            null_dyad_counts[dyad_key][b] = b_dyad_cnt.get(dyad_key, 0)
            null_dyad_usd[dyad_key][b] = b_dyad_val.get(dyad_key, 0.0)

        # Record for agencies
        for a in observed_agencies:
            s_dict = b_agency_vols.get(a, {})
            tot_v = sum(s_dict.values())
            if tot_v > 0:
                shares = np.array(list(s_dict.values())) / tot_v
                null_agency_hhi[a][b] = float(np.sum(shares ** 2))
                sorted_shares = np.sort(shares)[::-1]
                null_agency_cr3[a][b] = float(np.sum(sorted_shares[:3]))
            else:
                null_agency_hhi[a][b] = 0.0
                null_agency_cr3[a][b] = 0.0

    # 4. Standardize Dyad statistics
    dyad_rows = []
    for (a, s), obs_cnt in obs_dyad_counts.items():
        obs_val = obs_dyad_usd[(a, s)]
        counts_null = null_dyad_counts[(a, s)]
        usd_null = null_dyad_usd[(a, s)]

        mu_cnt = float(np.mean(counts_null))
        sd_cnt = float(np.std(counts_null))
        z_cnt = float((obs_cnt - mu_cnt) / sd_cnt) if sd_cnt > 0 else 0.0

        # Empirical two-sided p-value
        diff_cnt = np.abs(counts_null - mu_cnt)
        obs_diff = abs(obs_cnt - mu_cnt)
        p_val_cnt = float((1 + np.sum(diff_cnt >= obs_diff)) / (n_rewirings + 1))

        mu_val = float(np.mean(usd_null))
        sd_val = float(np.std(usd_null))
        z_val = float((obs_val - mu_val) / sd_val) if sd_val > 0 else 0.0

        dyad_rows.append({
            "agency": a,
            "canonical_supplier_id": s,
            "canonical_name": supplier_names.get(s, "UNKNOWN"),
            "obs_contracts": obs_cnt,
            "null_mean_contracts": round(mu_cnt, 3),
            "null_std_contracts": round(sd_cnt, 3),
            "z_contracts": round(z_cnt, 3),
            "p_contracts": round(p_val_cnt, 4),
            "obs_usd": round(obs_val, 2),
            "null_mean_usd": round(mu_val, 2),
            "null_std_usd": round(sd_val, 2),
            "z_usd": round(z_val, 3),
        })

    dyad_df = pd.DataFrame(dyad_rows).sort_values("z_contracts", ascending=False)

    # 5. Standardize Agency statistics
    agency_rows = []
    for a in observed_agencies:
        cnt_tot, vol_tot = agency_totals[a]
        obs_h = obs_agency_hhi[a]
        hhi_null = null_agency_hhi[a]
        mu_h = float(np.mean(hhi_null))
        sd_h = float(np.std(hhi_null))
        z_h = float((obs_h - mu_h) / sd_h) if sd_h > 0 else 0.0

        obs_c = obs_agency_cr3[a]
        cr3_null = null_agency_cr3[a]
        mu_c = float(np.mean(cr3_null))
        sd_c = float(np.std(cr3_null))
        z_c = float((obs_c - mu_c) / sd_c) if sd_c > 0 else 0.0

        agency_rows.append({
            "agency": a,
            "total_contracts": cnt_tot,
            "total_usd": round(vol_tot, 2),
            "obs_hhi": round(obs_h, 4),
            "null_mean_hhi": round(mu_h, 4),
            "null_std_hhi": round(sd_h, 4),
            "z_hhi": round(z_h, 3),
            "obs_cr3": round(obs_c, 4),
            "null_mean_cr3": round(mu_c, 4),
            "null_std_cr3": round(sd_c, 4),
            "z_cr3": round(z_c, 3),
        })

    agency_df = pd.DataFrame(agency_rows).sort_values("z_hhi", ascending=False)

    return {
        "dyad_results": dyad_df,
        "agency_results": agency_df,
        "summary": {
            "total_step_commercial_contracts": len(df_contracts),
            "total_strata": len(strata),
            "n_rewirings": n_rewirings,
            "random_seed": seed,
            "distinct_agencies": len(observed_agencies),
            "distinct_dyads": len(observed_dyad_keys),
        },
    }
