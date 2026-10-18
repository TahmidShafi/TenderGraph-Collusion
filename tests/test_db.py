"""Unit tests for DuckDB database initialization and operations."""

from pathlib import Path
import pytest
from src.ingestion.db import get_connection, init_db, log_audit_event


def test_init_db_in_memory():
    """Verify that init_db creates all required tables on an in-memory DuckDB connection."""
    con = init_db(":memory:")
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    assert "raw_contracts" in tables
    assert "mapped_projects" in tables
    assert "canonical_suppliers" in tables
    assert "audit_logs" in tables
    con.close()


def test_init_db_temp_file(tmp_path: Path):
    """Verify persistent database file creation and directory handling."""
    db_file = tmp_path / "subfolder" / "test_tendergraph.duckdb"
    con = init_db(db_file)
    assert db_file.exists()

    # Verify table schema columns for raw_contracts
    columns = [row[0] for row in con.execute("DESCRIBE raw_contracts").fetchall()]
    assert "contract_id" in columns
    assert "supplier_contract_amount_usd" in columns
    assert "contract_signing_date" in columns
    assert "review_type" in columns
    con.close()


def test_audit_log_persistence(tmp_path: Path):
    """Verify that log_audit_event persists JSON details into audit_logs table."""
    db_file = tmp_path / "audit_test.duckdb"
    init_db(db_file).close()

    log_audit_event(
        log_id="AUDIT-2026-001",
        audit_type="RESOLUTION_AUDIT",
        status="PASSED",
        details={"precision": 0.94, "sample_size": 200},
        metrics={"recall_ht": 0.88},
        db_path=db_file,
    )

    con = get_connection(db_file, read_only=True)
    rows = con.execute("SELECT log_id, audit_type, status, details FROM audit_logs").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "AUDIT-2026-001"
    assert rows[0][1] == "RESOLUTION_AUDIT"
    assert rows[0][2] == "PASSED"
    assert "0.94" in rows[0][3]
    con.close()
