# TenderGraph-Collusion (Frozen Design B Specification)

## 1. Scope & Hard Prohibitions
- **DO NOT** implement Graph Autoencoders (GAE), Node2Vec, or horizontal ring-bidding detectors (data is winner-only).
- **DO NOT** implement pooled Cattaneo density-discontinuity bunching tests or domestic BDT threshold detectors.
- **DO NOT** make causal claims on Prior-vs.-Post Review; all regime contrasts are descriptive within-agency associations controlling for log(USD) splines.
- **DO NOT** permute winner sequences across projects; permutations must stay strictly within `(project_id, procurement_category)`.

## 2. Temporal Sample Windows
- **Prior-vs.-Post Concentration Contrast:** Strictly FY2017–2026 STEP data (`0066876` + `DS00005`). Legacy FY2001–2016 (`0037797`) is truncated on Post-Review and excluded here.
- **Incumbency & Adjacent-Repeat Persistence:** FY2001–2026 only when restricted to `Prior-Review` contracts at or above an inflation-adjusted USD floor ($2M+), OR FY2017–2026 all review types.

## 3. Core Statistical Methods
1. **Entity Resolution:** Normalize supplier names -> RapidFuzz blocking & clustering -> compute `supplier_id` compression ratio -> audit 200 merged pairs (Precision >= 0.90) and 200 stratified unmerged near-neighbor pairs in [0.65, tau_cut) for Horvitz-Thompson Recall (Recall_HT >= 0.85 with 95% bootstrap CIs).
2. **Stratified BiCM Null:** Bipartite Configuration Model rewiring strictly within `(procurement_category, project_global_practice, 3_year_window)` strata, forbidding edges > 2x a supplier's maximum observed contract USD value.
3. **Adjacent Repeat Rate (R_bar_obs):** Compute mean adjacent repeat rate across 100 uniform random tie-breaks of same-date contract signings within `(project_id, procurement_category)`. Compare against 1,000 random sequence permutations.
4. **Power Simulation (Fixed-Marginal Noisy Cyclic Scheduling):** Fix exact winner counts n_i = round(N * p_i), arrange in a deterministic stride cycle minimizing adjacent repeats (bounded below by max(0, 2*n_max - N)), and apply floor((1 - gamma)*N) random pair-swaps for gamma in [0, 1].