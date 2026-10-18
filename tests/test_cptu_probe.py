"""Unit tests for CPTU / e-GP diagnostic probe."""

from src.ingestion.cptu_probe import CPTUDiagnosticReport, probe_cptu_portal


def test_cptu_report_dataclass():
    """Verify CPTUDiagnosticReport structure and dictionary conversion."""
    rep = CPTUDiagnosticReport(
        timestamp="2026-10-18T10:00:00Z",
        target_url="https://www.eprocure.gov.bd",
        portal_reachable=True,
        portal_status_code=200,
        robots_txt_status=401,
        robots_txt_disallowed=True,
        hierarchy_machine_parseable=False,
        status="SKIP_EXTENSION",
    )
    d = rep.to_dict()
    assert d["status"] == "SKIP_EXTENSION"
    assert d["portal_status_code"] == 200
    assert d["robots_txt_status"] == 401


def test_cptu_probe_execution():
    """Verify probe runs without raising unhandled exceptions and returns a valid report."""
    rep = probe_cptu_portal(timeout=5.0, log_to_db=False)
    assert isinstance(rep, CPTUDiagnosticReport)
    assert rep.status in ("PASS", "SKIP_EXTENSION")
    assert rep.target_url == "https://www.eprocure.gov.bd"
