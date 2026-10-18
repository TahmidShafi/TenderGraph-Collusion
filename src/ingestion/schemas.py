"""Pydantic schemas for World Bank contract ingestion and project-agency mappings."""

from datetime import date, datetime
from typing import Any, Literal
from dateutil import parser as date_parser
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Known placeholder names in World Bank procurement data that do not represent firm entities
DISALLOWED_SUPPLIER_PATTERNS = [
    "INDIVIDUAL CONSULTANT",
    "INDIVIDUAL CONSULTANTS",
    "INDIVIDUAL",
]


class RawWBContract(BaseModel):
    """Schema validating raw World Bank contract procurement records.

    Enforces strictly positive contract USD amounts (> 0), valid review types
    (Prior/Post), firm-level supplier identification (rejecting placeholder
    entries like 'INDIVIDUAL CONSULTANT'), and robust date parsing.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    contract_id: str = Field(..., min_length=1, description="Unique contract identifier")
    project_id: str = Field(..., min_length=1, description="World Bank Project ID")
    fiscal_year: int = Field(..., ge=1990, le=2100, description="Fiscal year of contract award")
    review_type: Literal["Prior", "Post"] = Field(..., description="Review regime: Prior or Post")
    procurement_category: str = Field(..., min_length=1, description="Procurement category (e.g. GOODS, WORKS)")
    procurement_method: str = Field(..., min_length=1, description="Procurement selection method")
    supplier_id: str = Field(..., min_length=1, description="Supplier/Vendor identifier")
    supplier_name: str = Field(..., min_length=1, description="Supplier firm name")
    supplier_country: str = Field(..., min_length=1, description="Supplier country")
    contract_signing_date: date = Field(..., description="Date of contract signing")
    supplier_contract_amount_usd: float = Field(
        ...,
        gt=0,
        description="Supplier contract amount in USD (must be strictly > 0)",
    )

    @model_validator(mode="before")
    @classmethod
    def derive_fiscal_year_from_date(cls, data: Any) -> Any:
        """World Bank fiscal year = year(signing_date) + 1 if month >= 7 else year(signing_date)."""
        if isinstance(data, dict):
            signing_date_val = data.get("contract_signing_date")
            if signing_date_val is not None:
                try:
                    parsed_date = cls.parse_signing_date(signing_date_val)
                    derived_fy = parsed_date.year + 1 if parsed_date.month >= 7 else parsed_date.year
                    data["fiscal_year"] = derived_fy
                except Exception:
                    pass
        return data

    @field_validator("supplier_id", mode="before")
    @classmethod
    def validate_supplier_id(cls, v: Any) -> str:
        """Ensure supplier_id is non-null and not empty/whitespace."""
        if v is None:
            raise ValueError("supplier_id cannot be None")
        val_str = str(v).strip()
        if not val_str:
            raise ValueError("supplier_id cannot be empty or whitespace")
        return val_str

    @field_validator("supplier_name")
    @classmethod
    def validate_supplier_name(cls, v: str) -> str:
        """Disallow individual consultant placeholders and empty firm names."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("supplier_name cannot be empty or whitespace")
        upper = cleaned.upper()
        for pattern in DISALLOWED_SUPPLIER_PATTERNS:
            if pattern in upper:
                raise ValueError(
                    f"Supplier name '{v}' is a placeholder ({pattern}) and cannot be evaluated as a commercial firm."
                )
        return cleaned

    @field_validator("review_type", mode="before")
    @classmethod
    def normalize_review_type(cls, v: Any) -> str:
        """Allow case-insensitive Prior/Post review values."""
        if isinstance(v, str):
            normalized = v.strip().capitalize()
            if normalized in ("Prior", "Post"):
                return normalized
        return v

    @field_validator("contract_signing_date", mode="before")
    @classmethod
    def parse_signing_date(cls, v: Any) -> date:
        """Parse date inputs from strings (ISO, US standard), datetime, or date objects."""
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            cleaned = v.strip()
            try:
                return date.fromisoformat(cleaned)
            except ValueError:
                pass
            try:
                return date_parser.parse(cleaned).date()
            except Exception as exc:
                raise ValueError(f"Unable to parse contract_signing_date from '{v}': {exc}") from exc
        raise ValueError(f"Unsupported type for contract_signing_date: {type(v)}")


class ProjectAgencyMap(BaseModel):
    """Schema validating World Bank project to implementing agency mapping."""

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    project_id: str = Field(..., min_length=1, description="World Bank Project ID")
    project_name: str = Field(..., min_length=1, description="Project title/name")
    implementing_agency_raw: str = Field(
        ...,
        min_length=1,
        description="Raw implementing agency string from World Bank metadata",
    )
    implementing_agency_canonical: str = Field(
        ...,
        min_length=1,
        description="Normalized/canonical implementing agency identifier",
    )
    global_practice: str = Field(
        ...,
        min_length=1,
        description="World Bank Global Practice (e.g. Transport, Energy, Water)",
    )
