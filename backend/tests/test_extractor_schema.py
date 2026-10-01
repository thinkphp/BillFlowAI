import unittest
import warnings
from decimal import Decimal

from google import genai
from google.genai import _transformers, types

from app.services.extractor import (
    find_explicit_total_amount,
    gemini_response_schema,
    find_previous_balance,
    invoice_extraction_prompt,
)


class GeminiResponseSchemaTests(unittest.TestCase):
    def test_schema_has_no_unsupported_defaults_or_union_null_types(self):
        schema = gemini_response_schema()

        def contains_unsupported_schema(value):
            if isinstance(value, dict):
                if "default" in value or "anyOf" in value:
                    return True
                return any(
                    contains_unsupported_schema(nested) for nested in value.values()
                )
            if isinstance(value, list):
                return any(contains_unsupported_schema(nested) for nested in value)
            return False

        self.assertFalse(contains_unsupported_schema(schema))
        self.assertIn("properties", schema)

    def test_gemini_sdk_compiles_response_schema(self):
        client = genai.Client(api_key="schema-validation-only")

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compiled = _transformers.t_schema(
                client._api_client, gemini_response_schema()
            )

        self.assertEqual(compiled.type, types.Type.OBJECT)

    def test_extraction_prompt_covers_romanian_labels_and_amount_formats(self):
        prompt = invoice_extraction_prompt()

        for instruction in (
            "Romanian",
            "CUI/CIF",
            "TVA",
            "Total de plată",
            "1.234,56",
            "Never invent, calculate",
            "not whether it passes arithmetic checks",
            "other_charges",
            "previous_balance",
            "take precedence over inferred totals",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)

    def test_reads_romanian_total_label_and_localized_amount(self):
        text = "Subtotal\n33,14 lei\nTVA\n6,30 lei\nTotal de plată\n40,12 lei"

        self.assertEqual(find_explicit_total_amount(text), Decimal("40.12"))

    def test_reads_total_label_without_diacritics_and_thousands_separator(self):
        text = "TOTAL DE PLATA: 1.234,56 RON"

        self.assertEqual(find_explicit_total_amount(text), Decimal("1234.56"))

    def test_ignores_previous_balance_labels(self):
        text = "Total de plată anterior: 99,00 lei\nSubtotal: 20,00 lei"

        self.assertIsNone(find_explicit_total_amount(text))

    def test_reads_previous_balance_from_summary_arithmetic(self):
        text = "\n".join(
            [
                "Valoare factură curentă",
                "Sold anterior neachitat",
                "Total de plată",
                "40,12 lei",
                "+",
                "131,14 lei",
                "=",
                "171,26 lei",
            ]
        )

        self.assertEqual(find_previous_balance(text), Decimal("131.14"))

    def test_summary_uses_amount_after_equals_for_total_due(self):
        text = "\n".join(
            [
                "Valoare factură curentă",
                "Sold anterior neachitat",
                "Total de plată",
                "40,12 lei",
                "+",
                "131,14 lei",
                "=",
                "171,26 lei",
            ]
        )

        self.assertEqual(find_explicit_total_amount(text), Decimal("171.26"))

    def test_detailed_current_invoice_total_is_not_used_as_overall_due(self):
        text = "\n".join(
            [
                "5. Total de plata factura curenta (5 = 4)",
                "lei",
                "40,12",
                "6. Sold la data emiterii facturii (facturi restante sau credit)",
                "lei",
                "131,14",
                "7. Total de plată (7 = 5 + 6)",
                "lei",
                "171,26",
            ]
        )

        self.assertEqual(find_explicit_total_amount(text), Decimal("171.26"))
        self.assertEqual(find_previous_balance(text), Decimal("131.14"))


if __name__ == "__main__":
    unittest.main()
