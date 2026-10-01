from app.config import settings
from app.schemas import InvoiceFields


TRACKED_FIELDS = (
    "supplier_name",
    "supplier_tax_id",
    "invoice_number",
    "issue_date",
    "due_date",
    "currency",
    "subtotal",
    "tax_amount",
    "other_charges",
    "previous_balance",
    "total_amount",
)


def validate_invoice(
    data: InvoiceFields, confidence: dict[str, float]
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    uncertain = [
        field
        for field in TRACKED_FIELDS
        if getattr(data, field) is None
        or confidence.get(field, 0) < settings.minimum_confidence
    ]

    if data.issue_date and data.due_date and data.due_date < data.issue_date:
        errors.append("The due date is earlier than the issue date.")
    if all(value is not None for value in (data.subtotal, data.tax_amount, data.total_amount)):
        expected_total = (
            data.subtotal
            + data.tax_amount
            + (data.other_charges or 0)
            + (data.previous_balance or 0)
        )
        if abs(expected_total - data.total_amount) > 0.02:
            errors.append(
                f"Total ({data.total_amount:.2f}) does not match subtotal, tax, and "
                f"additional charges, adjustments, and previous balance "
                f"({expected_total:.2f})."
            )
    if data.line_items and data.subtotal is not None:
        item_total = sum(item.amount or 0 for item in data.line_items)
        if abs(item_total - data.subtotal) > 0.02:
            errors.append(
                f"Line item sum ({item_total:.2f}) does not match subtotal "
                f"({data.subtotal:.2f})."
            )

    return uncertain, errors
