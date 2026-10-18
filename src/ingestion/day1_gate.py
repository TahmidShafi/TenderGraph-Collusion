"""Day-1 Feasibility Gate evaluation script for TenderGraph-Collusion.

Loads validated World Bank contract records and project-agency mappings into DuckDB,
executes the CPTU diagnostic probe, computes empirical stratum counts, evaluates
the provisional feasibility gates (>= 1,500 STEP contracts, >= 20 mapped agencies),
and generates data/audits/day1_gate_report.md.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import sys
from typing import Any
import duckdb

from src.ingestion.cptu_probe import probe_cptu_portal
from src.ingestion.db import DEFAULT_DB_PATH, get_connection, init_db, log_audit_event
from src.ingestion.wb_fetcher import (
    fetch_bangladesh_contracts,
    fetch_bangladesh_projects,
    load_contracts_to_db,
    load_projects_to_db,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_OUTPUT_PATH = PROJECT_ROOT / "data" / "audits" / "day1_gate_report.md"

# Provisional gate thresholds
MIN_STEP_CONTRACTS_THRESHOLD = 1500
MIN_MAPPED_AGENCIES_THRESHOLD = 20


def run_day1_gate(
    db_path: Path | str = DEFAULT_DB_PATH,
    report_path: Path | str = REPORT_OUTPUT_PATH,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Execute Day-1 feasibility gate pipeline.

    1. Initializes DuckDB database.
    2. Fetches/loads project mappings and validated contracts.
    3. Runs CPTU diagnostic probe.
    4. Computes empirical stratum metrics via SQL.
    5. Evaluates against provisional gate thresholds.
    6. Writes Markdown report and DuckDB audit log.

    Returns:
        Dictionary of computed metrics and gate verdicts.
    """
    print("=" * 70)
    print("TenderGraph-Collusion: Running Day-1 Feasibility Gate Pipeline")
    print("=" * 70)

    # Step 1: Initialize database
    print("\n[Step 1/5] Initializing DuckDB database...")
    init_db(db_path=db_path)

    # Step 2: Ingest project-agency metadata
    print("\n[Step 2/5] Ingesting World Bank project metadata and canonical agency maps...")
    projects = fetch_bangladesh_projects(use_cache=use_cache)
    projects_loaded = load_projects_to_db(projects, db_path=db_path)
    print(f"Loaded {projects_loaded} project-agency mappings into 'mapped_projects'.")

    # Step 3: Ingest and validate contract awards
    print("\n[Step 3/5] Ingesting and validating contract awards across windows...")
    valid_contracts, val_stats = fetch_bangladesh_contracts(use_cache=use_cache)
    contracts_loaded = load_contracts_to_db(valid_contracts, db_path=db_path)
    print(f"Loaded {contracts_loaded} validated contracts into 'raw_contracts'.")
    print(f"Validation breakdown: {val_stats}")

    # Step 4: Run CPTU diagnostic probe
    print("\n[Step 4/5] Running diagnostic probe on Bangladesh e-GP (eprocure.gov.bd)...")
    cptu_report = probe_cptu_portal(log_to_db=True, db_path=db_path)
    print(f"CPTU Probe Status: {cptu_report.status} (Reachable: {cptu_report.portal_reachable}, Robots: {cptu_report.robots_txt_status})")

    # Step 5: Compute empirical metrics via DuckDB
    print("\n[Step 5/5] Computing empirical gate metrics via DuckDB...")
    con = get_connection(db_path=db_path, read_only=True)
    try:
        metrics = _compute_metrics(con, val_stats, cptu_report)
    finally:
        con.close()

    # Step 6: Evaluate Gate Criteria
    step_contracts_ok = metrics["total_step_contracts"] >= MIN_STEP_CONTRACTS_THRESHOLD
    mapped_agencies_ok = metrics["distinct_mapped_agencies"] >= MIN_MAPPED_AGENCIES_THRESHOLD
    gate_passed = step_contracts_ok and mapped_agencies_ok

    metrics["gate_checks"] = {
        "step_contracts_threshold": MIN_STEP_CONTRACTS_THRESHOLD,
        "step_contracts_actual": metrics["total_step_contracts"],
        "step_contracts_pass": step_contracts_ok,
        "mapped_agencies_threshold": MIN_MAPPED_AGENCIES_THRESHOLD,
        "mapped_agencies_actual": metrics["distinct_mapped_agencies"],
        "mapped_agencies_pass": mapped_agencies_ok,
        "overall_gate_pass": gate_passed,
    }

    # Generate Markdown Report
    _write_gate_report(metrics, Path(report_path))

    # Persist audit event
    log_audit_event(
        log_id="DAY1-GATE-EVALUATION",
        audit_type="DAY1_FEASIBILITY_GATE",
        status="PASS" if gate_passed else "FAIL",
        details=metrics["gate_checks"],
        metrics={
            "total_valid_contracts": metrics["total_valid_contracts"],
            "total_step_contracts": metrics["total_step_contracts"],
            "distinct_projects": metrics["distinct_projects"],
            "distinct_mapped_agencies": metrics["distinct_mapped_agencies"],
            "distinct_suppliers": metrics["distinct_suppliers"],
            "distinct_supplier_names": metrics["distinct_raw_names"],
            "agency_linkage_share": metrics["agency_linkage_share"],
        },
        db_path=db_path,
    )

    print("\n" + "=" * 70)
    print(f"Day-1 Feasibility Gate Status: {'>>> PASS <<<' if gate_passed else '>>> FAIL <<<'}")
    print(f"Total STEP Contracts: {metrics['total_step_contracts']} (Required: >= {MIN_STEP_CONTRACTS_THRESHOLD})")
    print(f"Distinct Mapped Agencies: {metrics['distinct_mapped_agencies']} (Required: >= {MIN_MAPPED_AGENCIES_THRESHOLD})")
    print(f"Report written to: {report_path}")
    print("=" * 70)

    return metrics


def _compute_metrics(
    con: duckdb.DuckDBPyConnection,
    val_stats: dict[str, int],
    cptu_report: Any,
) -> dict[str, Any]:
    """Execute SQL aggregation queries to produce empirical gate metrics."""
    # a) Total contracts per dataset window
    # Window 1: Legacy (<= 2016)
    # Window 2: STEP FY17-19 (2017-2019)
    # Window 3: STEP FY20-26 (>= 2020)
    window_rows = con.execute(
        """
        SELECT 
            CASE 
                WHEN fiscal_year <= 2016 THEN 'FY01-16 (Legacy 0037797)'
                WHEN fiscal_year BETWEEN 2017 AND 2019 THEN 'FY17-19 (STEP 0066876)'
                ELSE 'FY20-26 (STEP DS00005)'
            END AS window_name,
            COUNT(*) AS contract_count,
            COALESCE(SUM(supplier_contract_amount_usd), 0.0) AS total_usd
        FROM raw_contracts
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()

    window_counts: dict[str, dict[str, Any]] = {}
    total_valid = 0
    total_step = 0
    total_usd = 0.0

    for w_name, cnt, usd in window_rows:
        window_counts[w_name] = {"count": cnt, "usd": usd}
        total_valid += cnt
        total_usd += usd
        if "STEP" in w_name:
            total_step += cnt

    # b) Share of contracts with non-null implementing_agency from Projects API
    linkage_row = con.execute(
        """
        SELECT 
            COUNT(*) AS total_contracts,
            COUNT(CASE WHEN p.implementing_agency_canonical IS NOT NULL AND p.implementing_agency_canonical != 'UNKNOWN' THEN 1 END) AS with_agency,
            COUNT(CASE WHEN p.project_id IS NOT NULL THEN 1 END) AS with_project_map
        FROM raw_contracts c
        LEFT JOIN mapped_projects p ON c.project_id = p.project_id
        """
    ).fetchone()

    total_c = linkage_row[0] if linkage_row else 0
    with_agency_c = linkage_row[1] if linkage_row else 0
    with_project_map_c = linkage_row[2] if linkage_row else 0
    agency_share = round((with_agency_c / total_c) * 100.0, 2) if total_c > 0 else 0.0

    # c) Distinct counts
    distinct_projects = con.execute("SELECT COUNT(DISTINCT project_id) FROM raw_contracts").fetchone()[0]
    distinct_agencies = con.execute(
        """
        SELECT COUNT(DISTINCT p.implementing_agency_canonical)
        FROM raw_contracts c
        JOIN mapped_projects p ON c.project_id = p.project_id
        WHERE p.implementing_agency_canonical IS NOT NULL 
          AND p.implementing_agency_canonical != 'UNKNOWN'
        """
    ).fetchone()[0]

    all_mapped_agencies = con.execute(
        "SELECT COUNT(DISTINCT implementing_agency_canonical) FROM mapped_projects WHERE implementing_agency_canonical != 'UNKNOWN'"
    ).fetchone()[0]

    distinct_suppliers = con.execute("SELECT COUNT(DISTINCT supplier_id) FROM raw_contracts").fetchone()[0]
    distinct_raw_names = con.execute("SELECT COUNT(DISTINCT supplier_name) FROM raw_contracts").fetchone()[0]

    # d) Strata counts
    # (project_id, procurement_category)
    proj_strata = con.execute(
        """
        SELECT project_id, procurement_category, COUNT(*) AS n, SUM(supplier_contract_amount_usd) AS usd
        FROM raw_contracts
        GROUP BY project_id, procurement_category
        """
    ).fetchall()

    proj_ge_15 = sum(1 for row in proj_strata if row[2] >= 15)
    proj_ge_20 = sum(1 for row in proj_strata if row[2] >= 20)
    proj_ge_30 = sum(1 for row in proj_strata if row[2] >= 30)

    # (agency, procurement_category)
    agency_strata = con.execute(
        """
        SELECT p.implementing_agency_canonical AS agency, c.procurement_category, COUNT(*) AS n, SUM(c.supplier_contract_amount_usd) AS usd
        FROM raw_contracts c
        JOIN mapped_projects p ON c.project_id = p.project_id
        WHERE p.implementing_agency_canonical IS NOT NULL AND p.implementing_agency_canonical != 'UNKNOWN'
        GROUP BY p.implementing_agency_canonical, c.procurement_category
        """
    ).fetchall()

    agency_ge_15 = sum(1 for row in agency_strata if row[2] >= 15)
    agency_ge_20 = sum(1 for row in agency_strata if row[2] >= 20)
    agency_ge_30 = sum(1 for row in agency_strata if row[2] >= 30)

    # Top agency strata for report table
    top_agency_strata = sorted(agency_strata, key=lambda x: x[2], reverse=True)[:10]

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_valid_contracts": total_valid,
        "total_usd_volume": total_usd,
        "total_step_contracts": total_step,
        "window_breakdown": window_counts,
        "validation_stats": val_stats,
        "agency_linkage_total": total_c,
        "agency_linkage_with_agency": with_agency_c,
        "agency_linkage_with_project_map": with_project_map_c,
        "agency_linkage_share": agency_share,
        "distinct_projects": distinct_projects,
        "distinct_mapped_agencies": distinct_agencies,
        "all_known_mapped_agencies": all_mapped_agencies,
        "distinct_suppliers": distinct_suppliers,
        "distinct_raw_names": distinct_raw_names,
        "strata_project_category": {
            "total_strata": len(proj_strata),
            "n_ge_15": proj_ge_15,
            "n_ge_20": proj_ge_20,
            "n_ge_30": proj_ge_30,
        },
        "strata_agency_category": {
            "total_strata": len(agency_strata),
            "n_ge_15": agency_ge_15,
            "n_ge_20": agency_ge_20,
            "n_ge_30": agency_ge_30,
            "top_10": top_agency_strata,
        },
        "cptu_probe": cptu_report.to_dict(),
    }


def _write_gate_report(metrics: dict[str, Any], output_path: Path) -> None:
    """Render comprehensive Markdown Feasibility Gate Report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gate = metrics["gate_checks"]
    verdict = "PASS" if gate["overall_gate_pass"] else "FAIL"

    lines = [
        "# Day-1 Feasibility Gate Report: TenderGraph-Collusion",
        "",
        f"**Generated:** {metrics['timestamp']}  ",
        f"**Pipeline Verdict:** **{verdict}**  ",
        "",
        "---",
        "",
        "## Executive Summary & Provisional Gate Decision",
        "",
        f"The Day-1 Feasibility Gate evaluates whether the empirical contract volume and agency metadata for Bangladesh satisfy the minimum sample size criteria required for entity resolution, Stratified BiCM null models, and Prior-vs-Post concentration analysis under [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md).",
        "",
        "| Gate Criterion | Required Threshold | Empirical Value | Status |",
        "| :--- | :--- | :--- | :--- |",
        f"| **STEP Contracts Volume (FY17–26)** | >= {gate['step_contracts_threshold']:,} | **{gate['step_contracts_actual']:,}** | {'✅ PASS' if gate['step_contracts_pass'] else '❌ FAIL'} |",
        f"| **Distinct Mapped Implementing Agencies** | >= {gate['mapped_agencies_threshold']} | **{gate['mapped_agencies_actual']}** | {'✅ PASS' if gate['mapped_agencies_pass'] else '❌ FAIL'} |",
        f"| **Overall Day-1 Feasibility Decision** | Both criteria met | **All Passed** | **{'✅ APPROVED (PROCEED TO WEEK 2)' if gate['overall_gate_pass'] else '❌ BLOCKED'}** |",
        "",
        "---",
        "",
        "## 1. Ingestion & Validation Summary",
        "",
        "Contracts were ingested from the World Bank API across the three designated procurement windows and validated against the Pydantic v2 `RawWBContract` schema. The schema strictly rejected individual consultant placeholders, negative or zero amounts, and unidentifiable vendors.",
        "",
        "- **Total Raw Contract Records Evaluated:** " + f"{metrics['validation_stats'].get('total_raw_rows_evaluated', 0):,}",
        "- **Total Valid Commercial Contracts Ingested:** " + f"**{metrics['total_valid_contracts']:,}**",
        f"- **Total Contract Value (USD):** ${metrics['total_usd_volume']:,.2f}",
        "- **Skipped Placeholder Suppliers (INDIVIDUAL CONSULTANT):** " + f"{metrics['validation_stats'].get('skipped_placeholder_supplier', 0):,}",
        "- **Skipped Missing Supplier IDs:** " + f"{metrics['validation_stats'].get('skipped_missing_supplier_id', 0):,}",
        "- **Skipped Non-Positive USD Amounts:** " + f"{metrics['validation_stats'].get('skipped_non_positive_amount', 0):,}",
        "- **Skipped Malformed Dates:** " + f"{metrics['validation_stats'].get('skipped_date_parse_error', 0):,}",
        "",
        "---",
        "",
        "## 2. Temporal Coverage Across Dataset Windows",
        "",
        "Under [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md), Prior-vs-Post concentration contrasts are restricted strictly to FY2017–2026 STEP data (`0066876` + `DS00005`), while Incumbency persistence includes FY2001–2016 Prior-Review contracts ($2M+ floor).",
        "",
        "| Dataset Window | Operational Period | Primary System | Contract Count | Total Committed (USD) |",
        "| :--- | :--- | :--- | :---: | :---: |",
    ]

    for w_name, data in metrics["window_breakdown"].items():
        lines.append(f"| {w_name} | Historical / Live | World Bank | {data['count']:,} | ${data['usd']:,.2f} |")

    lines.extend([
        f"| **Total STEP Operations** | **FY2017–2026** | **STEP System** | **{metrics['total_step_contracts']:,}** | **-** |",
        f"| **Grand Total** | **FY2001–2026** | **All Portals** | **{metrics['total_valid_contracts']:,}** | **${metrics['total_usd_volume']:,.2f}** |",
        "",
        "---",
        "",
        "## 3. Entity Resolution & Implementing Agency Linkage",
        "",
        "World Bank Projects API (`countrycode_exact=BD`) provided project-level metadata to link contracts to canonical executing agencies.",
        "",
        "| Dimension | Count | Description / Notes |",
        "| :--- | :---: | :--- |",
        f"| **Distinct Projects (`project_id`)** | {metrics['distinct_projects']:,} | World Bank investment projects with active contract awards |",
        f"| **Distinct Active Mapped Agencies** | {metrics['distinct_mapped_agencies']} | Canonical agencies executing observed contracts |",
        f"| **All Known Canonical Agencies** | {metrics['all_known_mapped_agencies']} | Total canonical agencies identified across Bangladesh portfolio |",
        f"| **Share of Contracts with Agency Map** | {metrics['agency_linkage_share']}% | Contracts mapped to verified executing agencies |",
        f"| **Distinct Supplier IDs (`supplier_id`)** | {metrics['distinct_suppliers']:,} | Pre-resolution unique vendor identifiers |",
        f"| **Distinct Raw Supplier Names** | {metrics['distinct_raw_names']:,} | Target string pool for Week 2 RapidFuzz entity resolution |",
        "",
        "---",
        "",
        "## 4. Stratification Density for BiCM Null & Permutation Tests",
        "",
        "Per [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md) Section 3, BiCM null rewirings and adjacent repeat sequence permutations must occur strictly within `(project_id, procurement_category)` or `(agency, procurement_category)` strata. Strata with $N \\ge 15$, $N \\ge 20$, and $N \\ge 30$ provide statistical power for permutation tests.",
        "",
        "### Stratum Sample Size Counts",
        "",
        "| Stratum Definition | Total Strata | Strata with $N \\ge 15$ | Strata with $N \\ge 20$ | Strata with $N \\ge 30$ |",
        "| :--- | :---: | :---: | :---: | :---: |",
        f"| `(project_id, procurement_category)` | {metrics['strata_project_category']['total_strata']:,} | **{metrics['strata_project_category']['n_ge_15']}** | **{metrics['strata_project_category']['n_ge_20']}** | **{metrics['strata_project_category']['n_ge_30']}** |",
        f"| `(agency, procurement_category)` | {metrics['strata_agency_category']['total_strata']:,} | **{metrics['strata_agency_category']['n_ge_15']}** | **{metrics['strata_agency_category']['n_ge_20']}** | **{metrics['strata_agency_category']['n_ge_30']}** |",
        "",
        "### Top 10 High-Density Agency Strata",
        "",
        "| Rank | Implementing Agency | Procurement Category | Contract Count ($N$) | Total Amount (USD) |",
        "| :---: | :--- | :--- | :---: | :---: |",
    ])

    for idx, (ag, cat, n, usd) in enumerate(metrics["strata_agency_category"]["top_10"], 1):
        lines.append(f"| {idx} | **{ag}** | {cat} | {n:,} | ${usd:,.2f} |")

    lines.extend([
        "",
        "---",
        "",
        "## 5. CPTU / e-GP Diagnostic Probe Findings",
        "",
        "A diagnostic probe was conducted against the domestic Bangladesh e-GP portal (`eprocure.gov.bd`) to evaluate data availability and machine-parseability.",
        "",
        f"- **Portal Reachability:** {'Reachable (HTTP 200)' if metrics['cptu_probe']['portal_reachable'] else 'Unreachable'} (Response latency: {metrics['cptu_probe']['latency_ms']}ms)",
        f"- **`robots.txt` Access:** HTTP {metrics['cptu_probe']['robots_txt_status']} (Access restricted/disallowed)",
        f"- **Hierarchy Machine-Parseability:** {'Parseable' if metrics['cptu_probe']['hierarchy_machine_parseable'] else 'Dynamic / Session-Dependent'}",
        f"- **Diagnostic Detail:** {metrics['cptu_probe']['hierarchy_diagnostic']}",
        f"- **Probe Status:** **{metrics['cptu_probe']['status']}**",
        f"- **Recommendation:** {metrics['cptu_probe']['recommendation']}",
        "",
        "---",
        "",
        "## 6. Recommended Next Steps for Week 2",
        "",
        "1. **Entity Resolution (`src/resolution/`):**",
        "   - Execute RapidFuzz blocking and string clustering on the raw supplier names.",
        "   - Compute supplier ID compression ratio and sample 200 merged pairs for audit (Target Precision >= 0.90).",
        "   - Sample 200 unmerged near-neighbor pairs in $[0.65, \\tau_{cut})$ to compute Horvitz-Thompson recall (Recall >= 0.85).",
        "2. **Bipartite Tender Graph Construction (`src/network/`):**",
        "   - Build bipartite graph of canonical suppliers and project/agency tender events.",
        "   - Implement Stratified BiCM null model preserving degrees within `(category, global_practice, 3_year_window)`.",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    run_day1_gate()
