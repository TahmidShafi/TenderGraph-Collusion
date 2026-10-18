# Day-1 Feasibility Gate Report: TenderGraph-Collusion

**Generated:** 2026-10-18T04:34:32.610662+00:00  
**Pipeline Verdict:** **PASS**  

---

## Executive Summary & Provisional Gate Decision

The Day-1 Feasibility Gate evaluates whether the empirical contract volume and agency metadata for Bangladesh satisfy the minimum sample size criteria required for entity resolution, Stratified BiCM null models, and Prior-vs-Post concentration analysis under [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md).

| Gate Criterion | Required Threshold | Empirical Value | Status |
| :--- | :--- | :--- | :--- |
| **STEP Contracts Volume (FY17–26)** | >= 1,500 | **9,240** | ✅ PASS |
| **Distinct Mapped Implementing Agencies** | >= 20 | **49** | ✅ PASS |
| **Overall Day-1 Feasibility Decision** | Both criteria met | **All Passed** | **✅ APPROVED (PROCEED TO WEEK 2)** |

---

## 1. Ingestion & Validation Summary

Contracts were ingested from the World Bank API across the three designated procurement windows and validated against the Pydantic v2 `RawWBContract` schema. The schema strictly rejected individual consultant placeholders, negative or zero amounts, and unidentifiable vendors.

- **Total Raw Contract Records Evaluated:** 11,644
- **Total Valid Commercial Contracts Ingested:** **9,374**
- **Total Contract Value (USD):** $11,781,209,660.59
- **Skipped Placeholder Suppliers (INDIVIDUAL CONSULTANT):** 2,249
- **Skipped Missing Supplier IDs:** 11
- **Skipped Non-Positive USD Amounts:** 0
- **Skipped Malformed Dates:** 0

---

## 2. Temporal Coverage Across Dataset Windows

Under [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md), Prior-vs-Post concentration contrasts are restricted strictly to FY2017–2026 STEP data (`0066876` + `DS00005`), while Incumbency persistence includes FY2001–2016 Prior-Review contracts ($2M+ floor).

| Dataset Window | Operational Period | Primary System | Contract Count | Total Committed (USD) |
| :--- | :--- | :--- | :---: | :---: |
| FY01-16 (Legacy 0037797) | Historical / Live | World Bank | 134 | $808,987,155.87 |
| FY17-19 (STEP 0066876) | Historical / Live | World Bank | 1,247 | $1,105,578,271.68 |
| FY20-26 (STEP DS00005) | Historical / Live | World Bank | 7,993 | $9,866,644,233.04 |
| **Total STEP Operations** | **FY2017–2026** | **STEP System** | **9,240** | **-** |
| **Grand Total** | **FY2001–2026** | **All Portals** | **9,374** | **$11,781,209,660.59** |

---

## 3. Entity Resolution & Implementing Agency Linkage

World Bank Projects API (`countrycode_exact=BD`) provided project-level metadata to link contracts to canonical executing agencies.

| Dimension | Count | Description / Notes |
| :--- | :---: | :--- |
| **Distinct Projects (`project_id`)** | 152 | World Bank investment projects with active contract awards |
| **Distinct Active Mapped Agencies** | 49 | Canonical agencies executing observed contracts |
| **All Known Canonical Agencies** | 57 | Total canonical agencies identified across Bangladesh portfolio |
| **Share of Contracts with Agency Map** | 98.47% | Contracts mapped to verified executing agencies |
| **Distinct Supplier IDs (`supplier_id`)** | 5,028 | Pre-resolution unique vendor identifiers |
| **Distinct Raw Supplier Names** | 4,683 | Target string pool for Week 2 RapidFuzz entity resolution |

---

## 4. Stratification Density for BiCM Null & Permutation Tests

Per [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md) Section 3, BiCM null rewirings and adjacent repeat sequence permutations must occur strictly within `(project_id, procurement_category)` or `(agency, procurement_category)` strata. Strata with $N \ge 15$, $N \ge 20$, and $N \ge 30$ provide statistical power for permutation tests.

### Stratum Sample Size Counts

| Stratum Definition | Total Strata | Strata with $N \ge 15$ | Strata with $N \ge 20$ | Strata with $N \ge 30$ |
| :--- | :---: | :---: | :---: | :---: |
| `(project_id, procurement_category)` | 408 | **135** | **114** | **75** |
| `(agency, procurement_category)` | 167 | **90** | **79** | **61** |

### Top 10 High-Density Agency Strata

| Rank | Implementing Agency | Procurement Category | Contract Count ($N$) | Total Amount (USD) |
| :---: | :--- | :--- | :---: | :---: |
| 1 | **LGED** | Works | 1,317 | $2,151,132,815.32 |
| 2 | **MOHFW** | Goods | 753 | $1,353,378,229.19 |
| 3 | **DPE** | Goods | 492 | $295,993,356.10 |
| 4 | **MOHFW** | Works | 404 | $183,677,702.93 |
| 5 | **BREB** | Goods | 338 | $183,718,025.94 |
| 6 | **DPHE** | Works | 304 | $210,123,531.79 |
| 7 | **LGED** | Consultant Services | 294 | $236,397,914.94 |
| 8 | **LGED** | Goods | 270 | $86,222,983.73 |
| 9 | **MOHFW** | Consultant Services | 219 | $317,446,534.29 |
| 10 | **DTE** | Goods | 204 | $15,259,993.45 |

---

## 5. CPTU / e-GP Diagnostic Probe Findings

A diagnostic probe was conducted against the domestic Bangladesh e-GP portal (`eprocure.gov.bd`) to evaluate data availability and machine-parseability.

- **Portal Reachability:** Reachable (HTTP 200) (Response latency: 45.83ms)
- **`robots.txt` Access:** HTTP 401 (Access restricted/disallowed)
- **Hierarchy Machine-Parseability:** Dynamic / Session-Dependent
- **Diagnostic Detail:** Office hierarchy dropdown relies on stateful dynamic AJAX/JSP session postbacks (static options count: 1); not cleanly machine-parseable without browser emulation.
- **Probe Status:** **SKIP_EXTENSION**
- **Recommendation:** Recommended action: SKIP_EXTENSION. eprocure.gov.bd restricts automated crawler access (robots.txt status: 401) and utilizes session-dependent JSP cascading dropdowns for procuring entities. Focus on frozen World Bank STEP data.

---

## 6. Recommended Next Steps for Week 2

1. **Entity Resolution (`src/resolution/`):**
   - Execute RapidFuzz blocking and string clustering on the raw supplier names.
   - Compute supplier ID compression ratio and sample 200 merged pairs for audit (Target Precision >= 0.90).
   - Sample 200 unmerged near-neighbor pairs in $[0.65, \tau_{cut})$ to compute Horvitz-Thompson recall (Recall >= 0.85).
2. **Bipartite Tender Graph Construction (`src/network/`):**
   - Build bipartite graph of canonical suppliers and project/agency tender events.
   - Implement Stratified BiCM null model preserving degrees within `(category, global_practice, 3_year_window)`.
