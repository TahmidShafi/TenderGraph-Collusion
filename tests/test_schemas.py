"""Unit tests for Pydantic validation schemas in TenderGraph-Collusion."""

from datetime import date, datetime
import pytest
from pydantic import ValidationError

from src.ingestion.schemas import ProjectAgencyMap, RawWBContract


@pytest.fixture
def valid_contract_payload() -> dict:
    """Fixture providing a baseline valid World Bank contract dictionary."""
    return {
        "contract_id": "WB-CON-1001",
        "project_id": "P168453",
        "fiscal_year": 2021,
        "review_type": "Prior",
        "procurement_category": "WORKS",
        "procurement_method": "Request for Bids",
        "supplier_id": "SUP-90210",
        "supplier_name": "Trans-National Infrastructure Corp",
        "supplier_country": "Kenya",
        "contract_signing_date": "2021-06-15",
        "supplier_contract_amount_usd": 2450000.0,
    }


def test_valid_contract_schema(valid_contract_payload: dict):
    """Verify that a well-formed contract dictionary parses and validates correctly."""
    contract = RawWBContract(**valid_contract_payload)
    assert contract.contract_id == "WB-CON-1001"
    assert contract.project_id == "P168453"
    assert contract.fiscal_year == 2021
    assert contract.review_type == "Prior"
    assert contract.procurement_category == "WORKS"
    assert contract.supplier_id == "SUP-90210"
    assert contract.supplier_name == "Trans-National Infrastructure Corp"
    assert contract.contract_signing_date == date(2021, 6, 15)
    assert contract.supplier_contract_amount_usd == 2450000.0


def test_review_type_normalization(valid_contract_payload: dict):
    """Verify review_type case-insensitivity and strict Prior/Post validation."""
    payload_lower = {**valid_contract_payload, "review_type": "prior"}
    contract = RawWBContract(**payload_lower)
    assert contract.review_type == "Prior"

    payload_upper = {**valid_contract_payload, "review_type": "POST"}
    contract = RawWBContract(**payload_upper)
    assert contract.review_type == "Post"

    payload_invalid = {**valid_contract_payload, "review_type": "Expedited"}
    with pytest.raises(ValidationError) as exc_info:
        RawWBContract(**payload_invalid)
    assert "review_type" in str(exc_info.value)


@pytest.mark.parametrize("missing_supplier_id", [None, "", "   "])
def test_missing_or_empty_supplier_id(valid_contract_payload: dict, missing_supplier_id):
    """Verify that null, empty, or whitespace-only supplier_id fails validation."""
    payload = {**valid_contract_payload, "supplier_id": missing_supplier_id}
    with pytest.raises(ValidationError) as exc_info:
        RawWBContract(**payload)
    assert "supplier_id" in str(exc_info.value)


def test_omitted_supplier_id(valid_contract_payload: dict):
    """Verify that omitting the supplier_id key entirely fails validation."""
    payload = valid_contract_payload.copy()
    del payload["supplier_id"]
    with pytest.raises(ValidationError) as exc_info:
        RawWBContract(**payload)
    assert "supplier_id" in str(exc_info.value)


@pytest.mark.parametrize(
    "placeholder_name",
    [
        "INDIVIDUAL CONSULTANT",
        "Individual Consultant",
        "individual consultant",
        "INDIVIDUAL CONSULTANTS",
        "Individual Consultant (Various)",
        "INDIVIDUAL CONSULTANT - ROAD SUPERVISION",
    ],
)
def test_individual_consultant_placeholder_rejected(
    valid_contract_payload: dict, placeholder_name: str
):
    """Verify that INDIVIDUAL CONSULTANT placeholder records are rejected."""
    payload = {**valid_contract_payload, "supplier_name": placeholder_name}
    with pytest.raises(ValidationError) as exc_info:
        RawWBContract(**payload)
    assert "supplier_name" in str(exc_info.value)
    assert "placeholder" in str(exc_info.value).lower()


def test_legitimate_consulting_firm_allowed(valid_contract_payload: dict):
    """Verify that legitimate corporate entity names are accepted."""
    payload = {**valid_contract_payload, "supplier_name": "Apex Engineering & Consulting Partners Ltd"}
    contract = RawWBContract(**payload)
    assert contract.supplier_name == "Apex Engineering & Consulting Partners Ltd"


@pytest.mark.parametrize("invalid_usd", [-1000.0, -0.01, 0.0, 0])
def test_negative_or_zero_usd_amount_rejected(valid_contract_payload: dict, invalid_usd):
    """Verify that negative or zero USD contract amounts fail validation."""
    payload = {**valid_contract_payload, "supplier_contract_amount_usd": invalid_usd}
    with pytest.raises(ValidationError) as exc_info:
        RawWBContract(**payload)
    assert "supplier_contract_amount_usd" in str(exc_info.value)


def test_positive_usd_amount_accepted(valid_contract_payload: dict):
    """Verify that strictly positive contract amounts pass validation."""
    payload = {**valid_contract_payload, "supplier_contract_amount_usd": 0.01}
    contract = RawWBContract(**payload)
    assert contract.supplier_contract_amount_usd == 0.01


@pytest.mark.parametrize(
    "date_input, expected_date",
    [
        ("2021-06-15", date(2021, 6, 15)),
        ("2021-06-15T00:00:00.000", date(2021, 6, 15)),
        ("06/15/2021", date(2021, 6, 15)),
        ("2021/06/15", date(2021, 6, 15)),
        (date(2021, 6, 15), date(2021, 6, 15)),
        (datetime(2021, 6, 15, 14, 30), date(2021, 6, 15)),
    ],
)
def test_date_parsing_formats(valid_contract_payload: dict, date_input, expected_date):
    """Verify that date parsing handles ISO strings, datetimes, dates, and slash formats."""
    payload = {**valid_contract_payload, "contract_signing_date": date_input}
    contract = RawWBContract(**payload)
    assert contract.contract_signing_date == expected_date


@pytest.mark.parametrize("invalid_date", ["invalid-date-string", "2021-99-99", ""])
def test_invalid_date_parsing_rejected(valid_contract_payload: dict, invalid_date):
    """Verify that malformed dates raise a ValidationError."""
    payload = {**valid_contract_payload, "contract_signing_date": invalid_date}
    with pytest.raises(ValidationError) as exc_info:
        RawWBContract(**payload)
    assert "contract_signing_date" in str(exc_info.value)


def test_project_agency_map_valid():
    """Verify ProjectAgencyMap schema validates with required fields."""
    mapping = ProjectAgencyMap(
        project_id="P168453",
        project_name="National Highway Connectivity Project",
        implementing_agency_raw="Ministry of Public Works and Transport",
        implementing_agency_canonical="MIN_PUBLIC_WORKS",
        global_practice="Transport",
    )
    assert mapping.project_id == "P168453"
    assert mapping.implementing_agency_canonical == "MIN_PUBLIC_WORKS"
    assert mapping.global_practice == "Transport"


@pytest.mark.parametrize(
    "field_to_empty",
    [
        "project_id",
        "project_name",
        "implementing_agency_raw",
        "implementing_agency_canonical",
        "global_practice",
    ],
)
def test_project_agency_map_empty_fields_rejected(field_to_empty: str):
    """Verify that empty/whitespace fields in ProjectAgencyMap fail validation."""
    data = {
        "project_id": "P168453",
        "project_name": "National Highway Connectivity Project",
        "implementing_agency_raw": "Ministry of Public Works",
        "implementing_agency_canonical": "MIN_PUBLIC_WORKS",
        "global_practice": "Transport",
    }
    data[field_to_empty] = "   "
    with pytest.raises(ValidationError):
        ProjectAgencyMap(**data)
