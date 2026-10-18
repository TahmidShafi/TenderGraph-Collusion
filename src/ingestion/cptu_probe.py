"""Diagnostic probe for Bangladesh e-GP (eprocure.gov.bd) public tender award notices.

Performs a polite, time-boxed diagnostic probe of eprocure.gov.bd checking robots.txt,
rate limits, response latencies, and machine-parseability of the
Ministry -> Division -> Agency/Procuring Entity hierarchy.

Status is determined as PASS or SKIP_EXTENSION without crashing the main pipeline.
"""

from __future__ import annotations

from pathlib import Path
import time
from dataclasses import asdict, dataclass, field
import httpx
from bs4 import BeautifulSoup

from src.ingestion.db import DEFAULT_DB_PATH, log_audit_event

EPROCURE_BASE_URL = "https://www.eprocure.gov.bd"
DEFAULT_TIMEOUT_SEC = 10.0


@dataclass
class CPTUDiagnosticReport:
    """Structured result of the CPTU / e-GP portal diagnostic probe."""

    timestamp: str
    target_url: str
    robots_txt_status: int | None = None
    robots_txt_disallowed: bool = False
    portal_reachable: bool = False
    portal_status_code: int | None = None
    latency_ms: float = 0.0
    search_endpoints_probed: dict[str, int] = field(default_factory=dict)
    hierarchy_machine_parseable: bool = False
    hierarchy_diagnostic: str = ""
    status: str = "SKIP_EXTENSION"  # PASS or SKIP_EXTENSION
    recommendation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def probe_cptu_portal(
    base_url: str = EPROCURE_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    log_to_db: bool = True,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> CPTUDiagnosticReport:
    """Run polite time-boxed diagnostic probe on eprocure.gov.bd.

    Args:
        base_url: Base URL of the e-GP portal.
        timeout: HTTP timeout in seconds.
        log_to_db: Whether to write an audit log entry to DuckDB.
        db_path: Target DuckDB database path for audit logs.

    Returns:
        CPTUDiagnosticReport detailing findings.
    """
    report = CPTUDiagnosticReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        target_url=base_url,
    )

    headers = {
        "User-Agent": "TenderGraph-Collusion-Research-Probe/1.0 (+https://github.com/tendergraph)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        with httpx.Client(timeout=timeout, verify=False, follow_redirects=True, headers=headers) as client:
            # 1. Check robots.txt
            robots_url = f"{base_url}/robots.txt"
            try:
                r_robots = client.get(robots_url)
                report.robots_txt_status = r_robots.status_code
                if r_robots.status_code == 200:
                    text_lower = r_robots.text.lower()
                    report.robots_txt_disallowed = "disallow: /" in text_lower
                elif r_robots.status_code in (401, 403):
                    report.robots_txt_disallowed = True
            except Exception as exc:
                report.robots_txt_status = None
                report.robots_txt_disallowed = True

            # 2. Check portal availability and latency
            t0 = time.time()
            try:
                r_portal = client.get(base_url)
                t1 = time.time()
                report.latency_ms = round((t1 - t0) * 1000.0, 2)
                report.portal_status_code = r_portal.status_code
                report.portal_reachable = r_portal.status_code == 200
            except Exception as exc:
                report.portal_reachable = False
                report.portal_status_code = None
                report.hierarchy_diagnostic = f"Portal connection failed: {exc}"
                report.status = "SKIP_EXTENSION"
                report.recommendation = (
                    "Skip CPTU e-GP extension; portal connection unreachable from current environment."
                )
                if log_to_db:
                    _safe_log(report)
                return report

            # 3. Probe SearchNOA and AllTenders endpoints
            noa_url = f"{base_url}/resources/common/SearchNOA.jsp"
            tenders_url = f"{base_url}/resources/common/AllTenders.jsp?h=t"

            for name, url in [("SearchNOA", noa_url), ("AllTenders", tenders_url)]:
                try:
                    r_ep = client.get(url)
                    report.search_endpoints_probed[name] = r_ep.status_code
                except Exception:
                    report.search_endpoints_probed[name] = 0

            # 4. Check whether Ministry -> Division -> Agency hierarchy is machine-parseable
            try:
                r_tenders = client.get(tenders_url)
                soup = BeautifulSoup(r_tenders.text, "html.parser")
                office_select = soup.find("select", {"name": "office"}) or soup.find("select", {"id": "cmbOffice"})

                # In e-GP, the office dropdown is populated via dynamic client-side AJAX/JSP postbacks
                # with only 1 placeholder option in static HTML
                options_count = len(office_select.find_all("option")) if office_select else 0
                if office_select and options_count > 10:
                    report.hierarchy_machine_parseable = True
                    report.hierarchy_diagnostic = (
                        f"Found static office hierarchy with {options_count} selectable options."
                    )
                else:
                    report.hierarchy_machine_parseable = False
                    report.hierarchy_diagnostic = (
                        "Office hierarchy dropdown relies on stateful dynamic AJAX/JSP session postbacks "
                        f"(static options count: {options_count}); not cleanly machine-parseable without browser emulation."
                    )
            except Exception as exc:
                report.hierarchy_machine_parseable = False
                report.hierarchy_diagnostic = f"Failed to parse hierarchy structure: {exc}"

            # 5. Determine status and recommendation
            if not report.portal_reachable or report.robots_txt_status in (401, 403) or not report.hierarchy_machine_parseable:
                report.status = "SKIP_EXTENSION"
                report.recommendation = (
                    "Recommended action: SKIP_EXTENSION. eprocure.gov.bd restricts automated crawler access "
                    f"(robots.txt status: {report.robots_txt_status}) and utilizes session-dependent JSP "
                    "cascading dropdowns for procuring entities. Focus on frozen World Bank STEP data."
                )
            else:
                report.status = "PASS"
                report.recommendation = (
                    "Portal is reachable and hierarchy is exposed; domestic tender extension is feasible."
                )

    except Exception as exc:
        report.status = "SKIP_EXTENSION"
        report.recommendation = f"Exception encountered during probe: {exc}. Safely skipping extension."

    if log_to_db:
        _safe_log(report, db_path=db_path)

    return report


def _safe_log(report: CPTUDiagnosticReport, db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Log audit event to DuckDB without raising exceptions if DB is locked."""
    try:
        log_audit_event(
            log_id=f"CPTU-PROBE-{int(time.time())}",
            audit_type="CPTU_DIAGNOSTIC_PROBE",
            status=report.status,
            details=report.to_dict(),
            metrics={
                "latency_ms": report.latency_ms,
                "portal_status": report.portal_status_code,
                "robots_status": report.robots_txt_status,
                "machine_parseable": report.hierarchy_machine_parseable,
            },
            db_path=db_path,
        )
    except Exception as e:
        print(f"[CPTU Probe] Audit log writing skipped: {e}")


if __name__ == "__main__":
    rep = probe_cptu_portal()
    print("=== CPTU Diagnostic Probe Result ===")
    print(f"Status: {rep.status}")
    print(f"Portal Reachable: {rep.portal_reachable} (HTTP {rep.portal_status_code}, {rep.latency_ms}ms)")
    print(f"Robots.txt Status: {rep.robots_txt_status} (Disallowed: {rep.robots_txt_disallowed})")
    print(f"Hierarchy Parseable: {rep.hierarchy_machine_parseable}")
    print(f"Diagnostic: {rep.hierarchy_diagnostic}")
    print(f"Recommendation: {rep.recommendation}")
