"""Supplier entity matcher and connected-component clustering.

Blocks candidate supplier pairs by supplier country and phonetic/token prefix,
computes RapidFuzz similarity scores (token_sort_ratio and Jaro-Winkler), evaluates
sensitivity across thresholds tau in {0.80, 0.85, 0.90, 0.95}, builds connected-component
clusters, and populates canonical_suppliers in DuckDB.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import duckdb
import networkx as nx
from rapidfuzz import distance, fuzz

from src.ingestion.db import DEFAULT_DB_PATH, get_connection
from src.resolution.normalizer import (
    clean_supplier_name,
    get_blocking_token,
    is_commercial_supplier,
)


@dataclass(frozen=True)
class SupplierCandidatePair:
    """Record representing a candidate comparison between two raw suppliers."""

    supplier_id_1: str
    name_1: str
    clean_name_1: str
    supplier_id_2: str
    name_2: str
    clean_name_2: str
    country: str
    token_sort_ratio: float
    jaro_winkler: float
    similarity_score: float


def load_unique_suppliers(
    db_path: Path | str = DEFAULT_DB_PATH,
    filter_non_commercial: bool = True,
) -> list[dict[str, Any]]:
    """Load distinct supplier records from DuckDB raw_contracts.

    Args:
        db_path: Path to the persistent DuckDB database.
        filter_non_commercial: Whether to exclude non-commercial placeholders and state utilities.

    Returns:
        List of dicts containing supplier_id, raw_name, clean_name, country, and block_key.
    """
    con = get_connection(db_path=db_path, read_only=True)
    try:
        rows = con.execute(
            """
            SELECT 
                supplier_id,
                supplier_name,
                supplier_country,
                COUNT(*) as contract_count,
                SUM(supplier_contract_amount_usd) as total_amount_usd
            FROM raw_contracts
            GROUP BY supplier_id, supplier_name, supplier_country
            ORDER BY contract_count DESC
            """
        ).fetchall()
    finally:
        con.close()

    # Deduplicate by supplier_id if a supplier has multiple name variations
    supplier_map: dict[str, dict[str, Any]] = {}
    for sid, name, country, cnt, amt in rows:
        sid_str = str(sid).strip()
        name_str = str(name).strip()
        country_str = (str(country).strip() if country else "BANGLADESH").upper()

        if filter_non_commercial and not is_commercial_supplier(name_str):
            continue

        if sid_str not in supplier_map:
            c_name = clean_supplier_name(name_str)
            supplier_map[sid_str] = {
                "supplier_id": sid_str,
                "raw_name": name_str,
                "clean_name": c_name,
                "country": country_str,
                "block_key": get_blocking_token(c_name),
                "contract_count": cnt,
                "total_amount_usd": amt,
            }
        else:
            supplier_map[sid_str]["contract_count"] += cnt
            supplier_map[sid_str]["total_amount_usd"] += amt

    return list(supplier_map.values())


def generate_candidate_pairs(
    suppliers: list[dict[str, Any]],
) -> list[SupplierCandidatePair]:
    """Block suppliers by country and initial token prefix, computing RapidFuzz scores.

    Candidate pairs are formed only within the same (country, block_key).
    Similarity is calculated as:
        similarity_score = 0.5 * (token_sort_ratio / 100.0) + 0.5 * JaroWinkler.similarity

    Args:
        suppliers: List of supplier dicts from load_unique_suppliers.

    Returns:
        List of SupplierCandidatePair dataclasses.
    """
    blocks: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for s in suppliers:
        key = (s["country"], s["block_key"])
        blocks[key].append(s)

    candidate_pairs: list[SupplierCandidatePair] = []

    for _, members in blocks.items():
        n_members = len(members)
        if n_members < 2:
            continue

        for i in range(n_members):
            s1 = members[i]
            for j in range(i + 1, n_members):
                s2 = members[j]
                if s1["supplier_id"] == s2["supplier_id"]:
                    continue

                tsr = fuzz.token_sort_ratio(s1["clean_name"], s2["clean_name"]) / 100.0
                jw = distance.JaroWinkler.similarity(s1["clean_name"], s2["clean_name"])
                sim = 0.5 * tsr + 0.5 * jw

                pair = SupplierCandidatePair(
                    supplier_id_1=s1["supplier_id"],
                    name_1=s1["raw_name"],
                    clean_name_1=s1["clean_name"],
                    supplier_id_2=s2["supplier_id"],
                    name_2=s2["raw_name"],
                    clean_name_2=s2["clean_name"],
                    country=s1["country"],
                    token_sort_ratio=round(tsr, 4),
                    jaro_winkler=round(jw, 4),
                    similarity_score=round(sim, 4),
                )
                candidate_pairs.append(pair)

    return candidate_pairs


def cluster_suppliers_at_threshold(
    suppliers: list[dict[str, Any]],
    candidate_pairs: list[SupplierCandidatePair],
    tau: float = 0.88,
) -> list[list[str]]:
    """Build connected-component clusters of supplier IDs at cutoff threshold tau.

    Args:
        suppliers: List of supplier records.
        candidate_pairs: List of candidate pairs with similarity scores.
        tau: Similarity threshold for merging candidate pairs.

    Returns:
        List of clusters, each containing a list of merged supplier_id strings.
    """
    graph = nx.Graph()
    for s in suppliers:
        graph.add_node(s["supplier_id"])

    for pair in candidate_pairs:
        if pair.similarity_score >= tau:
            graph.add_edge(pair.supplier_id_1, pair.supplier_id_2)

    return [list(comp) for comp in nx.connected_components(graph)]


def compute_id_compression_ratio(
    n_distinct_ids: int,
    n_clusters: int,
) -> float:
    """Calculate the ID-compression ratio: 1 - (n_fuzzy_clusters / n_distinct_supplier_ids).

    Args:
        n_distinct_ids: Total count of distinct raw supplier_ids.
        n_clusters: Number of connected-component canonical clusters.

    Returns:
        Compression ratio between 0.0 and 1.0.
    """
    if n_distinct_ids <= 0:
        return 0.0
    return 1.0 - (float(n_clusters) / float(n_distinct_ids))


def run_sensitivity_sweep(
    suppliers: list[dict[str, Any]],
    candidate_pairs: list[SupplierCandidatePair],
    thresholds: tuple[float, ...] = (0.80, 0.85, 0.90, 0.95),
) -> dict[float, dict[str, Any]]:
    """Evaluate clustering and compression across a sensitivity grid of thresholds.

    Args:
        suppliers: Unique supplier pool.
        candidate_pairs: Scored candidate pairs.
        thresholds: Sequence of tau cutoff values.

    Returns:
        Dict mapping threshold tau -> metrics dictionary.
    """
    n_distinct = len(suppliers)
    sweep_results: dict[float, dict[str, Any]] = {}

    for tau in thresholds:
        clusters = cluster_suppliers_at_threshold(suppliers, candidate_pairs, tau=tau)
        n_clusters = len(clusters)
        compression = compute_id_compression_ratio(n_distinct, n_clusters)
        merged_edges = sum(1 for p in candidate_pairs if p.similarity_score >= tau)

        sweep_results[tau] = {
            "tau": tau,
            "n_distinct_ids": n_distinct,
            "n_clusters": n_clusters,
            "compression_ratio": round(compression, 4),
            "merged_edges": merged_edges,
        }

    return sweep_results


def populate_canonical_suppliers_db(
    db_path: Path | str = DEFAULT_DB_PATH,
    tau_cut: float = 0.88,
    filter_non_commercial: bool = True,
) -> dict[str, Any]:
    """Execute full resolution pipeline and populate canonical_suppliers table in DuckDB.

    Args:
        db_path: Path to target DuckDB file.
        tau_cut: Default similarity threshold for canonical clustering.
        filter_non_commercial: Exclude placeholders and state agencies.

    Returns:
        Summary dictionary of clustering and compression metrics.
    """
    suppliers = load_unique_suppliers(db_path=db_path, filter_non_commercial=filter_non_commercial)
    candidate_pairs = generate_candidate_pairs(suppliers)
    clusters = cluster_suppliers_at_threshold(suppliers, candidate_pairs, tau=tau_cut)

    supplier_by_id = {s["supplier_id"]: s for s in suppliers}
    n_distinct = len(suppliers)
    n_clusters = len(clusters)
    compression = compute_id_compression_ratio(n_distinct, n_clusters)
    sensitivity = run_sensitivity_sweep(suppliers, candidate_pairs)

    # Prepare canonical rows for insertion
    canonical_rows: list[tuple[str, str, str, list[str], int, float]] = []
    for idx, comp in enumerate(clusters, start=1):
        can_id = f"CAN_SUP_{idx:05d}"

        # Choose canonical name: longest clean name or most frequent
        names = [supplier_by_id[sid]["clean_name"] for sid in comp if sid in supplier_by_id]
        canonical_name = max(names, key=len) if names else "UNKNOWN"

        # Modal country
        countries = [supplier_by_id[sid]["country"] for sid in comp if sid in supplier_by_id]
        modal_country = Counter(countries).most_common(1)[0][0] if countries else "BANGLADESH"

        # Totals across cluster members
        tot_cnt = sum(supplier_by_id[sid]["contract_count"] for sid in comp if sid in supplier_by_id)
        tot_amt = sum(supplier_by_id[sid]["total_amount_usd"] for sid in comp if sid in supplier_by_id)

        canonical_rows.append((
            can_id,
            canonical_name,
            modal_country,
            comp,
            tot_cnt,
            round(tot_amt, 2),
        ))

    # Persist into DuckDB
    con = get_connection(db_path=db_path, read_only=False)
    try:
        con.execute("DELETE FROM canonical_suppliers")
        con.executemany(
            """
            INSERT INTO canonical_suppliers (
                canonical_supplier_id,
                canonical_name,
                country,
                raw_supplier_ids,
                total_contracts,
                total_amount_usd
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            canonical_rows,
        )
    finally:
        con.close()

    return {
        "tau_cut": tau_cut,
        "n_distinct_raw_suppliers": n_distinct,
        "n_canonical_clusters": n_clusters,
        "compression_ratio": round(compression, 4),
        "candidate_pairs_evaluated": len(candidate_pairs),
        "sensitivity_sweep": sensitivity,
    }
