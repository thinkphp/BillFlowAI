from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvoiceLineItem(BaseModel):
    description: str = ""
    quantity: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    amount: float | None = Field(default=None, ge=0)


class InvoiceFields(BaseModel):
    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    invoice_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: float | None = Field(default=None, ge=0)
    tax_amount: float | None = Field(default=None, ge=0)
    other_charges: float | None = None
    previous_balance: float | None = Field(default=None, ge=0)
    total_amount: float | None = Field(default=None, ge=0)
    line_items: list[InvoiceLineItem] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        normalized = value.upper() if value else value
        if normalized is not None and (
            len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha()
        ):
            raise ValueError("Currency must be a 3-letter ISO 4217 code.")
        return normalized


class FieldConfidence(BaseModel):
    supplier_name: float | None = Field(default=None, ge=0, le=1)
    supplier_tax_id: float | None = Field(default=None, ge=0, le=1)
    invoice_number: float | None = Field(default=None, ge=0, le=1)
    issue_date: float | None = Field(default=None, ge=0, le=1)
    due_date: float | None = Field(default=None, ge=0, le=1)
    currency: float | None = Field(default=None, ge=0, le=1)
    subtotal: float | None = Field(default=None, ge=0, le=1)
    tax_amount: float | None = Field(default=None, ge=0, le=1)
    other_charges: float | None = Field(default=None, ge=0, le=1)
    previous_balance: float | None = Field(default=None, ge=0, le=1)
    total_amount: float | None = Field(default=None, ge=0, le=1)


class GeminiInvoiceExtraction(InvoiceFields):
    field_confidence: FieldConfidence = Field(default_factory=FieldConfidence)


class InvoiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    invoice_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: float | None = Field(default=None, ge=0)
    tax_amount: float | None = Field(default=None, ge=0)
    other_charges: float | None = None
    previous_balance: float | None = Field(default=None, ge=0)
    total_amount: float | None = Field(default=None, ge=0)
    line_items: list[InvoiceLineItem] | None = None


class InvoiceResponse(BaseModel):
    id: int
    filename: str
    status: str
    data: InvoiceFields
    confidence: dict[str, float]
    uncertain_fields: list[str]
    validation_errors: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
