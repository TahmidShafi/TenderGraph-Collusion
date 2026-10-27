# Week 3 Network Concentration & Sequence Persistence Report

**Generated:** 2026-10-27T16:22:14.117290+00:00  
**Provisional Statistical Power Gate Verdict:** **PASS**  

---

## Executive Summary & Statistical Feasibility Gate

Under [SPEC.md](file:///d:/tendergraph-collusion/SPEC.md) Section 2 and Section 3, Week 3 establishes two core inferential engines for detecting non-random procurement patterns:
1. **Bipartite Configuration Model (BiCM) Null:** Tests observed agency-supplier dyads and agency-level concentration against 1,000 degree-preserving, capacity-constrained null rewirings within `(procurement_category, global_practice, window_3yr)` strata.
2. **Adjacent Repeat Persistence Permutation Null:** Tests sequence persistence and anti-persistent rotation across 100 same-date tie-breaks within `(project_id, procurement_category)` strata, evaluating empirical statistical power under Fixed-Marginal Noisy Cyclic Scheduling and Stationary Incumbency Markov dynamics.

| Gate Criterion | Required Threshold | Empirical Value | Status |
| :--- | :---: | :---: | :---: |
| **Strata Achieving $\ge 80\%$ Power (Either Regime, $\alpha = 0.05$)** | $\ge 10$ strata | **128 of 128 (100.0%)** | ✅ PASS |
| **- Incumbency ($\delta = 0.50$) Powered Strata** | Benchmark | **128 of 128 (100.0%)** | ✅ POWERED |
| **- Rotation ($\gamma = 1.00$) Powered Strata** | Benchmark | **7 of 128 (5.5%)** | ℹ️ FRAGMENTED BOUND |
| **BiCM Commercial Graph Coverage (FY17–26)** | Commercial firms | **5,678 contracts** | ✅ PASS |
| **Overall Week 3 Gate Decision** | Powered strata $\ge 10$ | **Gate Cleared** | **✅ APPROVED (PROCEED TO WEEK 4)** |

---

## 1. Bipartite Configuration Model (BiCM) Concentration Analysis

The BiCM rewires edges while strictly preserving each agency's contract count, each supplier's contract count, and forbidding contract assignments exceeding $2.0\times$ a vendor's historical maximum USD contract award.

### Top 10 Most Concentrated Implementing Agencies (by HHI $z$-score)

| Implementing Agency | Total Contracts | Total Volume (USD) | Observed HHI | BiCM Null Mean HHI | HHI $z$-score | Top-3 Share ($CR_3$) | $CR_3$ $z$-score |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **DGHS** | 26 | $129,047,007.49 | 0.2916 | 0.1227 | **+7.77** | 87.9% | +6.39 |
| **DPHE** | 362 | $238,789,380.03 | 0.0286 | 0.0169 | **+6.97** | 22.5% | +4.56 |
| **DG_FOOD** | 42 | $361,907,008.80 | 0.1345 | 0.1075 | **+3.04** | 54.6% | +2.46 |
| **DAE** | 20 | $1,586,651.88 | 0.2250 | 0.1612 | **+3.02** | 73.5% | +3.60 |
| **DTE** | 230 | $17,048,551.64 | 0.0483 | 0.0347 | **+2.95** | 26.4% | +1.33 |
| **DSHE** | 16 | $4,716,361.52 | 0.4465 | 0.2611 | **+2.92** | 82.4% | +1.98 |
| **DLS** | 323 | $143,319,800.13 | 0.0332 | 0.0255 | **+2.40** | 25.2% | +2.96 |
| **PKSF** | 124 | $15,660,226.26 | 0.1120 | 0.1074 | **+2.31** | 45.9% | +1.09 |
| **NHA** | 77 | $12,881,053.28 | 0.1134 | 0.1134 | **+2.00** | 44.7% | +2.00 |
| **PGCB** | 126 | $752,732,920.82 | 0.0810 | 0.0745 | **+1.75** | 40.6% | +1.42 |

### Top 10 High-Concentration Agency-Supplier Dyads

| Agency | Canonical Supplier Firm | Contracts | Null Mean | Contract $z$-score | Empirical $p$-value | Total USD | Volume $z$-score |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **MOWCA** | GLOBAL BRAND (`CAN_SUP_00001`) | 1 | 0.01 | **+11.91** | 0.0080 | $3,662.40 | +10.66 |
| **DG_FOOD** | INTIMACY COMPUTER AND SOLUTIONS (`CAN_SUP_00221`) | 1 | 0.01 | **+9.48** | 0.0120 | $14,959.71 | +9.48 |
| **DAE** | SMART TECHNOLOGIES BANGLADESH (`CAN_SUP_00005`) | 4 | 0.27 | **+7.68** | 0.0010 | $109,810.29 | +7.10 |
| **IMED** | PARTEX FURNITURES INDUSTRIES (`CAN_SUP_00333`) | 1 | 0.02 | **+6.67** | 0.0230 | $15,803.63 | +9.09 |
| **UGC** | BANGLADESH SCIENCE HOUSE DHAKA (`CAN_SUP_00007`) | 3 | 0.20 | **+6.62** | 0.0010 | $604,553.22 | +1.94 |
| **UNKNOWN** | TAJEEM (`CAN_SUP_02032`) | 1 | 0.02 | **+6.38** | 0.0250 | $5,734.42 | +6.38 |
| **DSHE** | CORE KNOWLEDGE (`CAN_SUP_00833`) | 1 | 0.02 | **+6.38** | 0.0250 | $630,257.03 | +6.38 |
| **ELECTION_COMMISSION_SECRETARIAT** | COMPUTER SERVICES (`CAN_SUP_02821`) | 1 | 0.03 | **+6.12** | 0.0270 | $1,250,007.19 | +6.12 |
| **UGC** | BANGLADESH INSTITUTE OF DEVELOPMENT STUDIES BIDS (`CAN_SUP_00052`) | 8 | 3.11 | **+6.07** | 0.0010 | $1,036,954.55 | +5.14 |
| **DWASA** | SUNAM (`CAN_SUP_01971`) | 1 | 0.03 | **+5.79** | 0.0300 | $6,629.47 | +5.79 |

---

## 2. Sequence Persistence & Anti-Persistent Rotation Analysis

Evaluated across 100 uniform random orderings of same-date ties, comparing $\bar{R}_{\text{obs}}$ against 1,000 within-stratum permutations with Benjamini-Hochberg FDR correction ($q \le 0.10$).

- **Primary Sample (FY2017–2026 STEP):** 128 strata evaluated ($N \ge 10$); **37 statistically significant strata** at FDR $q \le 0.10$.
- **Longitudinal Sample (FY2001–2026 Prior $\ge \$2\text{M}$):** 21 strata evaluated; **3 statistically significant strata** at FDR $q \le 0.10$.

### Significant Persistence & Rotation Strata (Primary Sample, FDR $q \le 0.10$)

| Project ID | Category | Agency | $N$ | Distinct Vendors | $\bar{R}_{\text{obs}}$ | $E[R]$ | $z$-score | $p$-value | FDR $q$-value | Regime |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `P090807` | Goods | **DTE** | 157 | 70 | 0.115 | 0.051 | **+3.97** | 0.0010 | **0.0058** | PERSISTENT |
| `P106216` | Goods | **UGC** | 28 | 22 | 0.111 | 0.020 | **+3.62** | 0.0010 | **0.0058** | PERSISTENT |
| `P123828` | Works | **LGED** | 170 | 109 | 0.049 | 0.007 | **+6.46** | 0.0010 | **0.0058** | PERSISTENT |
| `P120583` | Goods | **DG_FOOD** | 12 | 8 | 0.364 | 0.153 | **+2.84** | 0.0010 | **0.0058** | PERSISTENT |
| `P131394` | Works | **DPE** | 36 | 15 | 0.292 | 0.087 | **+4.50** | 0.0010 | **0.0058** | PERSISTENT |
| `P133653` | Works | **LGED** | 230 | 152 | 0.070 | 0.005 | **+14.20** | 0.0010 | **0.0058** | PERSISTENT |
| `P129920` | Goods | **PGCB** | 41 | 22 | 0.224 | 0.029 | **+7.70** | 0.0010 | **0.0058** | PERSISTENT |
| `P149553` | Works | **MOA** | 62 | 32 | 0.249 | 0.031 | **+9.59** | 0.0010 | **0.0058** | PERSISTENT |
| `P149553` | Goods | **MOA** | 186 | 116 | 0.046 | 0.008 | **+6.10** | 0.0010 | **0.0058** | PERSISTENT |
| `P161996` | Works | **BFD** | 111 | 76 | 0.108 | 0.009 | **+11.15** | 0.0010 | **0.0058** | PERSISTENT |

---

## 3. Fixed-Marginal Power Simulation Results & Mathematical Calibration

Simulations conducted across all 128 eligible project-category strata under:
- **Fixed-Marginal Noisy Cyclic Scheduling:** $\gamma \in \{0.0, 0.25, 0.50, 0.75, 1.0\}$ with zero drift in market shares $p_i$.
- **Stationary Incumbency Markov Dynamics:** $\delta \in \{0.1, 0.3, 0.5\}$ preserving exact stationary shares $\mathbf{p}$.

- **Total Strata Evaluated ($N \ge 10$):** 128
- **Strata Achieving $\ge 80\%$ Statistical Power Under Incumbency ($\delta = 0.50$):** **128** (100.0%)
- **Strata Achieving $\ge 80\%$ Statistical Power Under Incumbency ($\delta = 0.30$):** **121** (94.5%)
- **Strata Achieving $\ge 80\%$ Statistical Power Under Cyclic Rotation ($\gamma = 1.00$):** **7** (5.5%)
- **Strata Achieving $\ge 80\%$ Statistical Power Under Cyclic Rotation ($\gamma = 0.75$):** **0** (0.0%)
- **Overall Strata Powered under Either Regime:** **128 of 128 (100.0%)**

> [!NOTE]
> **Calibration Note on Discrete Permutation Tails:**
> In a fixed-marginal permutation test of size $N$ with counts $n_i$, when vendor shares are fragmented (e.g. $N=10$, $n_i \le 2$), the expected permutation repeat rate $E[R] = \sum n_i(n_i-1) / [N(N-1)]$ is tiny, and $P(R = 0)$ is large ($> 0.50$). Consequently, zero repeats cannot produce an empirical $p$-value $\le 0.05$, bounding exact power for anti-persistent rotation to 0% in sparse strata. However, under Stationary Incumbency ($\delta=0.50$), repeat clustering generates strong positive deviations from $E[R] \approx 0$, achieving $\ge 80\%$ power across all 128 strata.

### Top 10 High-Power Strata Summary

| Project ID | Category | Agency | $N$ | Distinct Vendors | Power ($\gamma=1.0$) | Power ($\gamma=0.75$) | Power ($\delta=0.3$) | Power ($\delta=0.5$) | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `P173757` | Works | **MOHFW** | 248 | 132 | 100.0% | 13.5% | 100.0% | 100.0% | ✅ POWERED |
| `P133653` | Works | **LGED** | 230 | 152 | 0.0% | 1.5% | 100.0% | 100.0% | ✅ POWERED |
| `P161227` | Works | **DPHE** | 194 | 97 | 0.0% | 1.5% | 100.0% | 100.0% | ✅ POWERED |
| `P149553` | Goods | **MOA** | 186 | 116 | 0.0% | 1.0% | 100.0% | 100.0% | ✅ POWERED |
| `P123828` | Works | **LGED** | 170 | 109 | 0.0% | 2.0% | 100.0% | 100.0% | ✅ POWERED |
| `P167762` | Works | **LGED** | 170 | 87 | 0.0% | 0.5% | 100.0% | 100.0% | ✅ POWERED |
| `P090807` | Goods | **DTE** | 157 | 70 | 100.0% | 15.0% | 100.0% | 100.0% | ✅ POWERED |
| `P161246` | Works | **DLS** | 142 | 62 | 100.0% | 6.0% | 100.0% | 100.0% | ✅ POWERED |
| `P161246` | Goods | **DLS** | 129 | 54 | 100.0% | 9.0% | 100.0% | 100.0% | ✅ POWERED |
| `P150220` | Goods | **BWDB** | 123 | 86 | 0.0% | 1.0% | 100.0% | 100.0% | ✅ POWERED |

---
*Report generated automatically by `src.network.power_sim`.*