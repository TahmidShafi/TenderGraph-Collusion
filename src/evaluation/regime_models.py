"""Within-agency descriptive regression models and World Bank debarment cross-checks.

Implements under SPEC.md Section 1, Section 2, and Section 3:
1. Contract-level within-agency OLS regressions with HC3 robust and agency-clustered SEs:
   - Model 1: dyad_bicm_z_score ~ is_post_review + C(agency) + C(category) + C(method) + cr(log_usd, df=4)
   - Model 2: agency_supplier_share ~ is_post_review + C(agency) + C(category) + C(method) + cr(log_usd, df=4)
2. Controls for non-linear contract scale effects using natural cubic splines (df=4).
3. Sanity-check cross-referencing canonical Bangladeshi suppliers against World Bank
   sanctioned/debarred entities, reporting exact overlap strictly as a descriptive audit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import patsy
from rapidfuzz import fuzz
import statsmodels.api as sm
import statsmodels.formula.api as smf

from src.ingestion.db import DEFAULT_DB_PATH, PROJECT_ROOT, get_connection
from src.network.bicm_null import load_step_commercial_graph, run_bicm_null_simulation
from src.resolution.normalizer import clean_supplier_name, is_commercial_supplier

AUDITS_DIR = PROJECT_ROOT / "data" / "audits"
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_DEBARRED_PATH = RAW_DATA_DIR / "wb_debarred_firms_bangladesh.json"


def load_step_commercial_contracts(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """Load the primary FY2017-2026 STEP commercial contract sample (N = 5,678).

    Args:
        db_path: Path to DuckDB database file.

    Returns:
        DataFrame containing contract details, agency, and supplier IDs.
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
                rc.procurement_method,
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
            WHERE rc.fiscal_year >= 2017
            ORDER BY rc.contract_signing_date ASC
        """
        raw_df = con.execute(query).df()
    finally:
        con.close()

    valid_mask = raw_df["raw_supplier_name"].apply(is_commercial_supplier)
    df_clean = raw_df[valid_mask].copy()

    # Pre-derive key variables
    df_clean["is_post_review"] = (df_clean["review_type"] == "Post").astype(int)
    df_clean["amount_usd"] = df_clean["supplier_contract_amount_usd"].astype(float)
    df_clean["log_usd"] = np.log(df_clean["amount_usd"].clip(lower=1.0))

    # Agency supplier share: contracts won by supplier / total contracts awarded by agency
    agency_counts = df_clean.groupby("agency")["contract_id"].transform("count")
    supp_counts = df_clean.groupby(["agency", "canonical_supplier_id"])["contract_id"].transform("count")
    df_clean["agency_supplier_share"] = supp_counts / agency_counts

    return df_clean


def build_spline_features(
    df: pd.DataFrame,
    var_name: str = "log_usd",
    df_spline: int = 4,
) -> tuple[pd.DataFrame, list[str]]:
    """Build natural cubic spline basis columns with centered constraints.

    Uses patsy.cr(x, df=df_spline, constraints='center') to prevent multicollinearity
    with the intercept and categorical fixed effects.

    Args:
        df: Input DataFrame containing the continuous variable.
        var_name: Column name of continuous variable (e.g. log_usd).
        df_spline: Degrees of freedom (default 4).

    Returns:
        tuple of (DataFrame with added spline columns, list of spline column names).
    """
    df_out = df.copy()
    formula = f"cr({var_name}, df={df_spline}, constraints='center') - 1"
    spline_matrix = patsy.dmatrix(formula, data=df_out)

    spline_cols = []
    for i in range(spline_matrix.shape[1]):
        col_name = f"spline_{i}"
        df_out[col_name] = spline_matrix[:, i]
        spline_cols.append(col_name)

    return df_out, spline_cols


def prepare_regime_model_data(
    df_contracts: pd.DataFrame,
    dyad_bicm_results: pd.DataFrame | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    n_rewirings: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    """Merge BiCM dyad concentration z-scores and construct regression design columns.

    Args:
        df_contracts: Commercial STEP contracts (N = 5,678).
        dyad_bicm_results: Optional precomputed BiCM dyad results DataFrame.
        db_path: Path to database if BiCM null must be simulated.
        n_rewirings: Number of BiCM null rewirings if simulated.
        seed: Deterministic random seed.

    Returns:
        Prepared DataFrame ready for OLS regression estimation.
    """
    df_data = df_contracts.copy()

    if dyad_bicm_results is None:
        df_graph, max_usd_map = load_step_commercial_graph(db_path=db_path)
        bicm_sim = run_bicm_null_simulation(
            df_contracts=df_graph,
            max_usd_map=max_usd_map,
            n_rewirings=n_rewirings,
            seed=seed,
        )
        dyad_bicm_results = bicm_sim["dyad_results"]

    # Merge dyad BiCM z-score
    merged = df_data.merge(
        dyad_bicm_results[["agency", "canonical_supplier_id", "z_contracts"]],
        on=["agency", "canonical_supplier_id"],
        how="left",
    )
    merged.rename(columns={"z_contracts": "dyad_bicm_z_score"}, inplace=True)
    merged["dyad_bicm_z_score"] = merged["dyad_bicm_z_score"].fillna(0.0)

    # Build natural cubic splines of log(USD) with df=4
    df_featured, _ = build_spline_features(merged, var_name="log_usd", df_spline=4)
    return df_featured


def fit_within_agency_ols(
    df: pd.DataFrame,
    dep_var: str = "dyad_bicm_z_score",
    spline_cols: list[str] | None = None,
) -> dict[str, Any]:
    """Fit descriptive within-agency OLS regression with HC3 and clustered standard errors.

    Model:
        dep_var ~ is_post_review + C(agency) + C(procurement_category) + C(procurement_method) + splines

    Args:
        df: Prepared DataFrame with contract variables and splines.
        dep_var: Dependent variable ('dyad_bicm_z_score' or 'agency_supplier_share').
        spline_cols: List of spline column names.

    Returns:
        Dictionary summarizing parameter estimates, standard errors, p-values, and model stats.
    """
    if spline_cols is None:
        spline_cols = [c for c in df.columns if c.startswith("spline_")]

    spline_terms = " + ".join(spline_cols)
    formula = (
        f"{dep_var} ~ is_post_review + C(agency) + C(procurement_category) "
        f"+ C(procurement_method) + {spline_terms}"
    )

    # Fit with HC3 robust standard errors
    model_ols = smf.ols(formula, data=df)
    fit_hc3 = model_ols.fit(cov_type="HC3")

    # Fit with agency-clustered standard errors
    fit_clust = model_ols.fit(cov_type="cluster", cov_kwds={"groups": df["agency"]})

    coef_post = float(fit_hc3.params["is_post_review"])
    se_hc3 = float(fit_hc3.bse["is_post_review"])
    p_hc3 = float(fit_hc3.pvalues["is_post_review"])
    ci_hc3 = (float(fit_hc3.conf_int().loc["is_post_review", 0]), float(fit_hc3.conf_int().loc["is_post_review", 1]))

    se_clust = float(fit_clust.bse["is_post_review"])
    p_clust = float(fit_clust.pvalues["is_post_review"])
    ci_clust = (float(fit_clust.conf_int().loc["is_post_review", 0]), float(fit_clust.conf_int().loc["is_post_review", 1]))

    return {
        "dep_var": dep_var,
        "n_obs": int(fit_hc3.nobs),
        "r_squared": round(float(fit_hc3.rsquared), 4),
        "r_squared_adj": round(float(fit_hc3.rsquared_adj), 4),
        "n_agencies": int(df["agency"].nunique()),
        "coef_post_review": round(coef_post, 4),
        "se_hc3": round(se_hc3, 4),
        "p_value_hc3": round(p_hc3, 4),
        "ci_95_hc3": (round(ci_hc3[0], 4), round(ci_hc3[1], 4)),
        "se_clustered": round(se_clust, 4),
        "p_value_clustered": round(p_clust, 4),
        "ci_95_clustered": (round(ci_clust[0], 4), round(ci_clust[1], 4)),
        "fit_hc3": fit_hc3,
        "fit_clust": fit_clust,
    }


def estimate_all_regime_models(
    df_prepared: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Estimate both Model 1 (BiCM dyad z-score) and Model 2 (Agency supplier share).

    Args:
        df_prepared: Prepared contract dataset with splines and BiCM z-scores.

    Returns:
        Dictionary with 'model_1_bicm_z' and 'model_2_supplier_share' results.
    """
    m1 = fit_within_agency_ols(df_prepared, dep_var="dyad_bicm_z_score")
    m2 = fit_within_agency_ols(df_prepared, dep_var="agency_supplier_share")

    return {
        "model_1_bicm_z": m1,
        "model_2_supplier_share": m2,
    }


def cross_check_debarred_firms(
    canonical_suppliers_df: pd.DataFrame,
    debarred_source: list[dict[str, Any]] | Path | str | None = None,
    threshold: float = 92.0,
    anonymize: bool = False,
    sector_map: dict[str, str] | None = None,
    agency_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Sanity-check canonical suppliers against World Bank debarred entities in Bangladesh.

    Under SPEC.md Section 1, this cross-check is strictly descriptive. It matches
    canonical names against public verified records of entities sanctioned or debarred
    by the World Bank Group using strict normalized token-sort matching (threshold >= 92).

    Args:
        canonical_suppliers_df: DataFrame containing 'canonical_supplier_id' and 'canonical_name'.
        debarred_source: List of debarred dicts or Path to JSON snapshot.
        threshold: Strict RapidFuzz token sort similarity threshold (default 92.0).
        anonymize: Whether to mask raw names and display anonymized canonical IDs with context.
        sector_map: Optional mapping of canonical_supplier_id -> sector/procurement_category.
        agency_map: Optional mapping of canonical_supplier_id -> primary implementing agency.

    Returns:
        DataFrame of matched entities with match confidence and debarment metadata.
    """
    if debarred_source is None:
        debarred_source = DEFAULT_DEBARRED_PATH

    if isinstance(debarred_source, (str, Path)):
        p = Path(debarred_source)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                debarred_list = json.load(f)
        else:
            debarred_list = []
    else:
        debarred_list = debarred_source

    matches = []
    for d in debarred_list:
        raw_firm_name = str(d.get("firm_name", "")).strip()
        ref_id = str(d.get("reference_id", d.get("citation", "WB_SANCTION_REF")))
        d_clean = clean_supplier_name(raw_firm_name)
        if not d_clean:
            continue

        for _, row in canonical_suppliers_df.iterrows():
            can_id = str(row.get("canonical_supplier_id", ""))
            can_name = str(row.get("canonical_name", ""))
            s_clean = clean_supplier_name(can_name)
            if not s_clean:
                continue

            # Strict normalized token sort ratio only (fuzz.token_sort_ratio >= threshold)
            sort_score = float(fuzz.token_sort_ratio(d_clean, s_clean))

            if sort_score >= threshold:
                agency = (agency_map or {}).get(can_id, "Multiple")
                sector = (sector_map or {}).get(can_id, "Commercial")
                anon_label = f"{can_id} (Agency: {agency}, Sector: {sector})"

                matches.append({
                    "canonical_supplier_id": can_id,
                    "canonical_name": anon_label if anonymize else can_name,
                    "anonymized_label": anon_label,
                    "debarred_reference": ref_id if anonymize else raw_firm_name,
                    "debarred_firm_name": raw_firm_name,
                    "match_score": round(sort_score, 1),
                    "country": d.get("country", "Bangladesh"),
                    "citation": d.get("citation", d.get("grounds", "Public Decision")),
                    "grounds": d.get("grounds", d.get("citation", "Sanctions Board Record")),
                    "status": d.get("status", "Published Record"),
                    "debarment_period": d.get("debarment_period", "N/A"),
                })

    df_matches = pd.DataFrame(matches)
    if not df_matches.empty:
        df_matches = df_matches.sort_values("match_score", ascending=False).drop_duplicates(
            subset=["canonical_supplier_id", "debarred_firm_name"]
        )
    return df_matches
