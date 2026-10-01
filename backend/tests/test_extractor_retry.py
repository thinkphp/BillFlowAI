import unittest
from unittest.mock import MagicMock, patch

from google.genai.errors import ServerError

from app.services.extractor import ExtractionFailed, extract_invoice


class GeminiRetryTests(unittest.TestCase):
    @patch("app.services.extractor.genai.Client")
    @patch("app.services.extractor.settings")
    def test_explicit_romanian_total_overrides_model_amount(
        self, settings, client_factory
    ):
        settings.gemini_api_key = "test-key"
        client = MagicMock()
        client_factory.return_value = client
        response = MagicMock()
        response.text = (
            '{"total_amount":40.12,"field_confidence":{"total_amount":1.0}}'
        )
        client.models.generate_content.return_value = response

        result = extract_invoice(
            "Valoare factură curentă\nSold anterior neachitat\nTotal de plată\n"
            "40,12 lei\n+\n131,14 lei\n=\n171,26 lei"
        )

        self.assertEqual(result.total_amount, 171.26)
        self.assertEqual(result.previous_balance, 131.14)
        self.assertEqual(result.field_confidence.total_amount, 0.99)

    @patch("app.services.extractor.time.sleep")
    @patch("app.services.extractor.genai.Client")
    @patch("app.services.extractor.settings")
    def test_retries_transient_unavailability(self, settings, client_factory, sleep):
        settings.gemini_api_key = "test-key"
        client = MagicMock()
        client_factory.return_value = client
        response = MagicMock()
        response.text = '{"field_confidence": {}}'
        client.models.generate_content.side_effect = [
            ServerError(503, {"error": {"message": "busy"}}),
            response,
        ]

        result = extract_invoice("Invoice text")

        self.assertIsNotNone(result)
        self.assertEqual(client.models.generate_content.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("app.services.extractor.time.sleep")
    @patch("app.services.extractor.genai.Client")
    @patch("app.services.extractor.settings")
    def test_returns_retryable_failure_after_retry_limit(
        self, settings, client_factory, sleep
    ):
        settings.gemini_api_key = "test-key"
        client = MagicMock()
        client_factory.return_value = client
        client.models.generate_content.side_effect = ServerError(
            503, {"error": {"message": "busy"}}
        )

        with self.assertRaises(ExtractionFailed) as raised:
            extract_invoice("Invoice text")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(client.models.generate_content.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])


if __name__ == "__main__":
    unittest.main()
