# Week 2 Entity Resolution & Horvitz-Thompson Audit Report

**Generated:** 2026-10-18T04:59:58.523565+00:00  
**Entity Resolution Verdict:** **PASS**  

---

## Executive Summary & Statistical Feasibility

Under [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md) Section 3, entity resolution must satisfy two rigorous statistical quality gates before constructing bipartite supplier-project networks and computing concentration metrics:
1. **Precision Gate:** Audited sample precision $\ge 0.90$ (controlling false merges).
2. **Horvitz-Thompson Recall Gate:** Stratum-weighted Horvitz-Thompson Recall $\ge 0.85$ with 95% bootstrap confidence intervals (controlling false negatives in near-neighbor similarity bands).

| Gate Criterion | Required Threshold | Empirical Value | 95% Bootstrap CI | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Precision (Merged Pairs at $\tau = 0.88$)** | $\ge 0.90$ | **93.50%** | [90.00%, 96.50%] | ✅ PASS |
| **Horvitz-Thompson Recall ($s \in [0.65, 0.88)$)** | $\ge 0.85$ | **90.60%** | [83.05%, 97.31%] | ✅ PASS |
| **Overall Resolution Gate** | Both criteria met | **All Passed** | - | **✅ APPROVED (PROCEED TO WEEK 3)** |

---

## 1. Data Hygiene & Temporal Re-Bucketing

A rigorous data-hygiene audit of `raw_contracts` was executed to eliminate year-label artifacts in historical World Bank data dumps:
- **World Bank Fiscal Year Re-derivation:** Derived strictly as $\text{Year}(\text{signing\_date}) + 1$ if $\text{Month} \ge 7$ else $\text{Year}(\text{signing\_date})$.
- **Closed Historical Projects Protected:** Pre-2014 projects (e.g., `P037857`, `P041887`, `P074841`, `P071794`, `P071435`) sit strictly in **FY2001–2016** and do not bleed into FY2017–2026.
- **STEP Window Purity:** In FY2017–2026, **99.38%** of contracts (5,647 out of 5,682) originate directly from live STEP endpoints (`0066876` and `DS00005`), and **100%** possess explicit `Prior` or `Post` review regimes.

| Window | Contract Count | Total Value (USD) | Distinct Projects |
| :--- | :---: | :---: | :---: |
| FY2001-2016 | 3,692 | $4,440,132,724.49 | 89 |
| FY2017-2019 | 1,500 | $1,522,255,000.05 | 50 |
| FY2020-2026 | 4,182 | $5,818,821,936.05 | 74 |

---

## 2. Supplier Normalization & Entity Disambiguation

- **Total Distinct Raw Commercial Suppliers:** 5,020
- **Resolved Canonical Supplier Entities:** 3,967
- **ID-Compression Ratio:** **20.98%** (from 5020 raw IDs down to 3967 canonical entities).
- **State Utilities / Implementing Agencies Filtered:** State-owned entities erroneously listed as vendors (e.g., `Power Grid Company of Bangladesh`, `Local Government Engineering Department`, `National Water and Sewerage`, `Bangladesh Computer Council`) were strictly excluded from commercial supplier-concentration metrics.

### Sensitivity Sweep Across Similarity Thresholds $\tau$

| Cutoff $\tau$ | Canonical Clusters | Compressed IDs | ID Compression Ratio | Merged Edges |
| :---: | :---: | :---: | :---: | :---: |
| $\tau = 0.80$ | 3,755 | 1,265 | 25.20% | 2,299 |
| $\tau = 0.85$ | 3,908 | 1,112 | 22.15% | 1,938 |
| $\tau = 0.90$ | 3,994 | 1,026 | 20.44% | 1,730 |
| $\tau = 0.95$ | 4,104 | 916 | 18.25% | 1,466 |

---

## 3. Horvitz-Thompson Stratified Recall Audit

Sub-threshold candidate pairs were blocked by country and phonetic/token prefix, then partitioned into three similarity strata within $[0.65, 0.88)$:
- **Band A $[0.80, 0.88)$:** Near-cutoff band capturing minor spelling variants and multi-word vendor tokens.
- **Band B $[0.72, 0.80)$:** Intermediate band capturing partial abbreviation and word reordering.
- **Band C $[0.65, 0.72)$:** Broad near-neighbor baseline band.

| Stratum Band | Population Size ($N_h$) | Sample Size ($n_h$) | Sampling Weight ($N_h / n_h$) | Sample False Negatives ($fn_h$) | Population False Negatives ($\widehat{FN}_h$) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `Band_A_[0.80_0.88)` | 504 | 70 | 7.20 | 5 | 36.0 |
| `Band_B_[0.72_0.80)` | 1,347 | 70 | 19.24 | 2 | 38.5 |
| `Band_C_[0.65_0.72)` | 2,987 | 60 | 49.78 | 2 | 99.6 |

- **Estimated Total True Positives ($\widehat{TP}$):** 1678.3
- **Estimated Total Horvitz-Thompson False Negatives ($\widehat{FN}_{\text{HT}}$):** 174.1
- **Stratum-Weighted Horvitz-Thompson Recall:** **90.60%** (95% CI: [83.05%, 97.31%])

---

## 4. Top 10 High-Concentration Canonical Supplier Clusters

| Canonical ID | Canonical Supplier Firm | Country | Merged Raw IDs | Total Contracts | Total Volume (USD) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `CAN_SUP_00005` | **SMART TECHNOLOGIES BANGLADESH** | BANGLADESH | 10 | 93 | $61,605,897.22 |
| `CAN_SUP_00001` | **GLOBAL BRAND** | BANGLADESH | 6 | 65 | $19,886,693.65 |
| `CAN_SUP_00013` | **FLORA** | BANGLADESH | 10 | 55 | $23,511,516.09 |
| `CAN_SUP_00022` | **ESSENTIAL DRUGS EDCL** | BANGLADESH | 6 | 44 | $63,027,821.44 |
| `CAN_SUP_00024` | **KOKUSAI LINKS** | JAPAN | 5 | 38 | $27,267,922.31 |
| `CAN_SUP_00002` | **UNITED NATIONS CHILDREN S FUND UNICEF** | WORLD | 1 | 37 | $474,330,234.94 |
| `CAN_SUP_00004` | **PROMA PRESS AND PUBLICATIONS** | BANGLADESH | 2 | 37 | $17,523,149.90 |
| `CAN_SUP_00003` | **BRIGHT PRINTING PRESS** | BANGLADESH | 2 | 37 | $17,090,913.78 |
| `CAN_SUP_00007` | **BANGLADESH SCIENCE HOUSE DHAKA** | BANGLADESH | 5 | 37 | $13,624,573.48 |
| `CAN_SUP_00021` | **INSTITUTE OF WATER MODELLING IWM** | BANGLADESH | 6 | 32 | $18,016,042.93 |

---
*Report generated automatically by `src.resolution.audit_sampler`.*