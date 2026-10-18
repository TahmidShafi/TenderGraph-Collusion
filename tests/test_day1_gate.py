"""Unit tests for Day-1 Feasibility Gate evaluation pipeline using real empirical data."""

from pathlib import Path
import pytest

from src.ingestion.day1_gate import run_day1_gate
from src.ingestion.db import init_db


def test_day1_gate_real_pipeline(tmp_path: Path):
    """Verify Day-1 Gate pipeline execution, metric computation, and report generation using real data."""
    test_db = tmp_path / "test_day1.duckdb"
    test_report = tmp_path / "test_report.md"

    # Execute gate pipeline against an isolated test DuckDB file using actual cached raw data
    metrics = run_day1_gate(db_path=test_db, report_path=test_report, use_cache=True)

    # Verify report was generated
    assert test_report.exists()
    content = test_report.read_text(encoding="utf-8")
    assert "# Day-1 Feasibility Gate Report" in content
    assert "Executive Summary & Provisional Gate Decision" in content
    assert "**Pipeline Verdict:** **PASS**" in content

    # Verify empirical metrics computed from real World Bank contracts
    assert metrics["gate_checks"]["overall_gate_pass"] is True
    assert metrics["total_valid_contracts"] > 8000
    assert metrics["total_step_contracts"] >= 1500
    assert metrics["distinct_mapped_agencies"] >= 20
    assert metrics["distinct_projects"] > 50
    assert metrics["distinct_suppliers"] > 1000
