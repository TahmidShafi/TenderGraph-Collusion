"""Sequence persistence and anti-persistent rotation engine.

Evaluates adjacent repeat rates (R_bar_obs) across uniform random tie-breaks of
same-date contract signings within (project_id, procurement_category) strata,
comparing against 1,000 random winner multiset permutations with Benjamini-Hochberg
FDR correction under SPEC.md Section 2 and Section 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from src.ingestion.db import DEFAULT_DB_PATH, get_connection
from src.resolution.normalizer import is_commercial_supplier


def load_persistence_samples(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the two distinct analysis samples defined in SPEC.md Section 2.

    Sample A: Primary Sample — FY2017-2026 STEP all review types.
    Sample B: Longitudinal Prior-Review Sample — FY2001-2026 restricted to
              review_type == 'Prior' and supplier_contract_amount_usd >= $2M.

    Args:
        db_path: Path to DuckDB database.

    Returns:
        tuple of (df_primary_step, df_longitudinal_prior)
    """
    con = get_connection(db_path=db_path, read_only=True)
    try:
        query = """
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
                rc.procurement_category,
                rc.review_type,
                rc.fiscal_year,
                rc.contract_signing_date,
                rc.supplier_contract_amount_usd,
                sl.canonical_supplier_id,
                sl.canonical_name,
                rc.supplier_name as raw_supplier_name,
                COALESCE(mp.implementing_agency_canonical, 'UNKNOWN') as agency
            FROM raw_contracts rc
            INNER JOIN supplier_lookup sl ON rc.supplier_id = sl.raw_supplier_id
            LEFT JOIN mapped_projects mp ON rc.project_id = mp.project_id
            ORDER BY rc.project_id, rc.procurement_category, rc.contract_signing_date ASC
        """
        all_contracts = con.execute(query).df()
    finally:
        con.close()

    # Filter out any non-commercial / state-agency suppliers
    valid_mask = all_contracts["raw_supplier_name"].apply(is_commercial_supplier)
    df_clean = all_contracts[valid_mask].copy()

    # Sample A: Primary Sample (FY2017-2026 STEP all review types)
    df_primary = df_clean[df_clean["fiscal_year"] >= 2017].copy()

    # Sample B: Longitudinal Prior-Review Sample (FY2001-2026 Prior >= $2M)
    df_longitudinal = df_clean[
        (df_clean["review_type"] == "Prior")
        & (df_clean["supplier_contract_amount_usd"] >= 2_000_000.0)
    ].copy()

    return df_primary, df_longitudinal


def compute_tied_adjacent_repeats(
    df_stratum: pd.DataFrame,
    n_tie_breaks: int = 100,
    seed: int = 42,
) -> float:
    """Compute mean adjacent repeat rate R_bar_obs across uniform random tie-breaks.

    For contracts signed on the exact same date, co-dated ties are ordered uniformly
    at random across n_tie_breaks iterations.

    R = (1 / (N - 1)) * sum_{t=2}^N I(W_t == W_{t-1})

    Args:
        df_stratum: DataFrame of contracts for a single stratum sorted by signing date.
        n_tie_breaks: Number of random permutations of tied co-dated subsets.
        seed: Deterministic random seed.

    Returns:
        Mean adjacent repeat rate R_bar_obs in [0.0, 1.0].
    """
    N = len(df_stratum)
    if N < 2:
        return 0.0

    # Group rows by contract_signing_date to identify tied groups
    date_groups = []
    current_date = None
    current_items: list[str] = []

    for _, row in df_stratum.iterrows():
        d = row["contract_signing_date"]
        s = str(row["canonical_supplier_id"])
        if d == current_date:
            current_items.append(s)
        else:
            if current_items:
                date_groups.append(current_items)
            current_date = d
            current_items = [s]
    if current_items:
        date_groups.append(current_items)

    # Check if there are any ties with > 1 element
    has_ties = any(len(g) > 1 for g in date_groups)
    if not has_ties:
        winners = [g[0] for g in date_groups]
        repeats = sum(1 for i in range(1, N) if winners[i] == winners[i - 1])
        return float(repeats / (N - 1))

    rng = np.random.default_rng(seed)
    repeat_rates = np.empty(n_tie_breaks, dtype=float)

    for b in range(n_tie_breaks):
        ordered_winners: list[str] = []
        for g in date_groups:
            if len(g) == 1:
                ordered_winners.append(g[0])
            else:
                shuffled = [g[idx] for idx in rng.permutation(len(g))]
                ordered_winners.extend(shuffled)

        repeats = sum(1 for i in range(1, N) if ordered_winners[i] == ordered_winners[i - 1])
        repeat_rates[b] = float(repeats / (N - 1))

    return float(np.mean(repeat_rates))


def evaluate_stratum_persistence(
    df_stratum: pd.DataFrame,
    n_tie_breaks: int = 100,
    n_permutations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Test sequence persistence against 1,000 within-stratum permutations.

    Args:
        df_stratum: Contracts for a single (project_id, procurement_category) stratum.
        n_tie_breaks: Number of same-date tie breaks.
        n_permutations: Number of random permutations of the winner multiset.
        seed: Random seed.

    Returns:
        Dictionary of observed rate, null expectation, z-score, p-value, and metadata.
    """
    N = len(df_stratum)
    project_id = str(df_stratum["project_id"].iloc[0])
    category = str(df_stratum["procurement_category"].iloc[0])
    agency = str(df_stratum["agency"].iloc[0])

    # 1. Compute R_bar_obs across random tie-breaks
    r_bar_obs = compute_tied_adjacent_repeats(df_stratum, n_tie_breaks=n_tie_breaks, seed=seed)

    # 2. Extract winner multiset
    winners = df_stratum["canonical_supplier_id"].astype(str).to_numpy()
    unique_suppliers, counts = np.unique(winners, return_counts=True)
    n_unique = len(unique_suppliers)
    n_max = int(np.max(counts))

    # Theoretical expected repeat rate under random permutation:
    # E[R] = sum n_i(n_i - 1) / (N(N - 1))
    theo_exp = float(np.sum(counts * (counts - 1)) / (N * (N - 1))) if N > 1 else 0.0

    # Theoretical minimum repeats: max(0, 2*n_max - N)
    theo_min_repeats = max(0, 2 * n_max - N)
    theo_min_rate = float(theo_min_repeats / (N - 1)) if N > 1 else 0.0

    # 3. Permutation null distribution
    rng = np.random.default_rng(seed)
    null_repeats = np.empty(n_permutations, dtype=float)

    for p in range(n_permutations):
        shuffled = rng.permutation(winners)
        reps = np.sum(shuffled[1:] == shuffled[:-1])
        null_repeats[p] = float(reps / (N - 1))

    null_mean = float(np.mean(null_repeats))
    null_std = float(np.std(null_repeats))
    z_score = float((r_bar_obs - null_mean) / null_std) if null_std > 0 else 0.0

    # Empirical two-sided p-value
    abs_diffs = np.abs(null_repeats - null_mean)
    obs_diff = abs(r_bar_obs - null_mean)
    p_value = float((1 + np.sum(abs_diffs >= obs_diff)) / (n_permutations + 1))

    # Regimes
    direction = "PERSISTENT" if r_bar_obs > null_mean else ("ROTATION" if r_bar_obs < null_mean else "NEUTRAL")

    return {
        "project_id": project_id,
        "procurement_category": category,
        "agency": agency,
        "N": N,
        "distinct_suppliers": n_unique,
        "n_max_winner": n_max,
        "r_bar_obs": round(r_bar_obs, 4),
        "null_mean": round(null_mean, 4),
        "theo_expected": round(theo_exp, 4),
        "theo_min_rate": round(theo_min_rate, 4),
        "null_std": round(null_std, 4),
        "z_score": round(z_score, 3),
        "p_value": round(p_value, 4),
        "direction": direction,
    }


def run_persistence_analysis(
    df_sample: pd.DataFrame,
    min_contracts: int = 10,
    n_permutations: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    """Execute persistence permutation analysis across all eligible strata with FDR correction.

    Args:
        df_sample: Contract sample (e.g. Primary STEP or Longitudinal Prior-Review).
        min_contracts: Minimum sample size threshold (N >= 10).
        n_permutations: Number of null permutations per stratum.
        seed: Random seed.

    Returns:
        DataFrame sorted by ascending FDR q-values.
    """
    grouped = df_sample.groupby(["project_id", "procurement_category"])
    results = []

    for (proj_id, cat), group_df in grouped:
        if len(group_df) < min_contracts:
            continue
        sorted_stratum = group_df.sort_values("contract_signing_date", ascending=True)
        res = evaluate_stratum_persistence(
            df_stratum=sorted_stratum,
            n_tie_breaks=100,
            n_permutations=n_permutations,
            seed=seed,
        )
        results.append(res)

    if not results:
        return pd.DataFrame()

    df_res = pd.DataFrame(results)

    # Benjamini-Hochberg FDR correction
    p_vals = df_res["p_value"].to_numpy()
    _, q_vals, _, _ = multipletests(p_vals, alpha=0.10, method="fdr_bh")
    df_res["fdr_q_value"] = np.round(q_vals, 4)

    # Reorder columns
    cols = [
        "project_id",
        "procurement_category",
        "agency",
        "N",
        "distinct_suppliers",
        "r_bar_obs",
        "null_mean",
        "z_score",
        "p_value",
        "fdr_q_value",
        "direction",
    ]
    return df_res[cols].sort_values("p_value", ascending=True)
