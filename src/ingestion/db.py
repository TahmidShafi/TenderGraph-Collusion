"""DuckDB storage layer for TenderGraph-Collusion.

Manages persistent database initialization, schema definition, and table
creation for raw World Bank contracts, mapped projects, canonical suppliers,
and audit logs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import duckdb

# Derive repository root relative to this module: <repo_root>/src/ingestion/db.py -> <repo_root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "processed" / "tendergraph.duckdb"

SCHEMA_DDL = """
-- Raw World Bank contract procurement records
CREATE TABLE IF NOT EXISTS raw_contracts (
    contract_id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    fiscal_year INTEGER NOT NULL,
    review_type VARCHAR NOT NULL,
    procurement_category VARCHAR NOT NULL,
    procurement_method VARCHAR NOT NULL,
    supplier_id VARCHAR NOT NULL,
    supplier_name VARCHAR NOT NULL,
    supplier_country VARCHAR NOT NULL,
    contract_signing_date DATE NOT NULL,
    supplier_contract_amount_usd DOUBLE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- World Bank project-to-implementing agency mappings
CREATE TABLE IF NOT EXISTS mapped_projects (
    project_id VARCHAR PRIMARY KEY,
    project_name VARCHAR NOT NULL,
    implementing_agency_raw VARCHAR NOT NULL,
    implementing_agency_canonical VARCHAR NOT NULL,
    global_practice VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Canonical supplier entities resolved via RapidFuzz clustering
CREATE TABLE IF NOT EXISTS canonical_suppliers (
    canonical_supplier_id VARCHAR PRIMARY KEY,
    canonical_name VARCHAR NOT NULL,
    country VARCHAR,
    raw_supplier_ids VARCHAR[],
    total_contracts INTEGER DEFAULT 0,
    total_amount_usd DOUBLE DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit logs for entity resolution, BiCM simulations, and permutation tests
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id VARCHAR PRIMARY KEY,
    audit_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    details VARCHAR,
    metrics VARCHAR,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection(
    db_path: Path | str = DEFAULT_DB_PATH,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Connect to the persistent DuckDB database, creating directories if needed.

    Args:
        db_path: Path to the .duckdb database file.
        read_only: Whether to open the database in read-only mode.

    Returns:
        duckdb.DuckDBPyConnection: Active connection to DuckDB.
    """
    path_obj = Path(db_path)
    if not read_only:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(database=str(path_obj), read_only=read_only)


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Initialize database tables and constraints if they do not already exist.

    Args:
        db_path: Target path for the persistent DuckDB database.

    Returns:
        duckdb.DuckDBPyConnection: Active connection with initialized tables.
    """
    con = get_connection(db_path=db_path, read_only=False)
    con.execute(SCHEMA_DDL)
    return con


def log_audit_event(
    log_id: str,
    audit_type: str,
    status: str,
    details: dict[str, Any] | str | None = None,
    metrics: dict[str, Any] | str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Persist an audit event or evaluation run log into DuckDB."""
    details_str = json.dumps(details) if isinstance(details, dict) else details
    metrics_str = json.dumps(metrics) if isinstance(metrics, dict) else metrics

    con = get_connection(db_path=db_path, read_only=False)
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO audit_logs (log_id, audit_type, status, details, metrics)
            VALUES (?, ?, ?, ?, ?)
            """,
            [log_id, audit_type, status, details_str, metrics_str],
        )
    finally:
        con.close()


if __name__ == "__main__":
    conn = init_db()
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    print(f"Database initialized at: {DEFAULT_DB_PATH}")
    print(f"Active tables: {tables}")
    conn.close()
