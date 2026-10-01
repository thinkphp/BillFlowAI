import unittest
from datetime import date

from app.schemas import InvoiceFields
from app.services.validation import TRACKED_FIELDS, validate_invoice


class InvoiceValidationTests(unittest.TestCase):
    def test_balanced_invoice_passes(self):
        invoice = InvoiceFields(
            supplier_name="Furnizor SRL",
            supplier_tax_id="RO12345678",
            invoice_number="F-100",
            issue_date=date(2026, 9, 1),
            due_date=date(2026, 9, 30),
            currency="ron",
            subtotal=100,
            tax_amount=19,
            other_charges=0,
            previous_balance=0,
            total_amount=119,
        )

        uncertain, errors = validate_invoice(
            invoice, {field: 0.95 for field in TRACKED_FIELDS}
        )

        self.assertEqual(uncertain, [])
        self.assertEqual(errors, [])
        self.assertEqual(invoice.currency, "RON")

    def test_missing_and_low_confidence_fields_are_uncertain(self):
        invoice = InvoiceFields(supplier_name="Furnizor SRL")

        uncertain, errors = validate_invoice(invoice, {"supplier_name": 0.5})

        self.assertIn("supplier_name", uncertain)
        self.assertIn("invoice_number", uncertain)
        self.assertEqual(errors, [])

    def test_mismatched_totals_and_dates_are_reported(self):
        invoice = InvoiceFields(
            issue_date=date(2026, 9, 30),
            due_date=date(2026, 9, 1),
            subtotal=100,
            tax_amount=19,
            total_amount=120,
        )

        _, errors = validate_invoice(invoice, {})

        self.assertEqual(len(errors), 2)
        self.assertTrue(any("due date" in error for error in errors))
        self.assertTrue(any("Total" in error for error in errors))

    def test_line_item_sum_must_match_subtotal(self):
        invoice = InvoiceFields(
            subtotal=100,
            line_items=[{"description": "Serviciu", "amount": 90}],
        )

        _, errors = validate_invoice(invoice, {})

        self.assertTrue(any("Line item sum" in error for error in errors))

    def test_previous_balance_is_included_in_total_check(self):
        invoice = InvoiceFields(
            subtotal=33.14,
            tax_amount=6.30,
            other_charges=0,
            previous_balance=0.68,
            total_amount=40.12,
        )

        _, errors = validate_invoice(invoice, {})

        self.assertFalse(any("Total" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
