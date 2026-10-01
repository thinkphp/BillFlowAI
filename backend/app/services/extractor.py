import logging
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import settings
from app.schemas import GeminiInvoiceExtraction


logger = logging.getLogger(__name__)
MAX_TRANSIENT_RETRIES = 2
RETRYABLE_STATUS_CODES = {429, 503}
TOTAL_LABEL = re.compile(
    r"\b(?:total\s+(?:de\s+)?plata|total\s+de\s+achitat|valoare\s+totala\s+de\s+plata)\b"
)
PREVIOUS_BALANCE_LABELS = (
    re.compile(r"\bsold\s+la\s+data\s+emiterii\s+facturii\b"),
    re.compile(r"\bsold\s+anterior\s+neachitat\b"),
)
AMOUNT_TOKEN = re.compile(
    r"(?<![\w/.-])[-+]?(?:\d{1,3}(?:[ .\u00a0]\d{3})+|\d+)(?:[,.]\d{2})(?![\d/.-])"
    r"|(?<![\w/.-])[-+]?\d+(?:[,.]\d{2})?(?![\d/.-])"
)


class ExtractionUnavailable(Exception):
    pass


class ExtractionFailed(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def gemini_response_schema() -> dict[str, Any]:
    schema = GeminiInvoiceExtraction.model_json_schema()

    def normalize_schema(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            alternatives = value.get("anyOf")
            if alternatives:
                non_null_alternatives = [
                    option
                    for option in alternatives
                    if option.get("type") != "null"
                ]
                if len(non_null_alternatives) == 1:
                    title = value.get("title")
                    value.update(non_null_alternatives[0])
                    value["nullable"] = True
                    if title:
                        value["title"] = title
                    value.pop("anyOf", None)
            for nested in value.values():
                normalize_schema(nested)
        elif isinstance(value, list):
            for nested in value:
                normalize_schema(nested)

    normalize_schema(schema)
    return schema


def invoice_extraction_prompt() -> str:
    return """
Extract invoice fields from the supplied text or PDF. Invoices may be written in Romanian
or English. Read Romanian labels and abbreviations, including Furnizor, CUI/CIF, Număr
factură, Data emiterii, Scadență, Valoare fără TVA, TVA, Total de plată, Sold, and Lei.

Never invent, calculate, or "correct" a value to make totals agree. Copy amounts as
printed and convert them to JSON numbers: Romanian decimal commas (for example 1.234,56)
mean 1234.56; a dot between groups of three digits may be a thousands separator. Normalize
dates to YYYY-MM-DD and currency to ISO 4217 (RON for Romanian lei). Use null for missing
or unreadable values. Distinguish the current invoice total from prior balances, payments,
and account balances; select the amount due for this invoice, not an unrelated account
balance. Extract the net amount of any separately shown fees, adjustments, discounts, or
other charges into other_charges (discounts may be negative). Extract an outstanding prior
balance shown as "Sold anterior neachitat" or "Sold la data emiterii facturii" into
previous_balance, not other_charges. Use 0 only when the invoice clearly shows no such
amount; use null if unclear. Do not assume subtotal + tax equals total without accounting
for other_charges and previous_balance.

If the document has a value explicitly labelled "Total de plată", "Total plata",
"Total de achitat", or "Valoare totală de plată", copy that adjacent amount exactly to
total_amount. On summary pages where "Valoare factură curentă + Sold anterior neachitat =
Total de plată" is shown, use the amount after the equals sign. Do not use the current
invoice amount when a distinct total due is printed. A table row labelled "Total de plata
factura curenta" is only the current invoice amount and is not the overall total due.
Explicit total-due labels take precedence over inferred totals and arithmetic.

For every extracted top-level field, report field_confidence from 0 to 1 based on how
clearly that value is visible in the source, not whether it passes arithmetic checks. Use a
low score for blurry, ambiguous, or inferred values; use null when a value is not present.
subtotal is the pre-tax amount, tax_amount is the tax amount explicitly shown,
other_charges is the net sum of additional charges and adjustments, and total_amount is
the total amount payable as printed, including previous_balance when shown.
previous_balance is the outstanding amount carried from earlier invoices. Each line-item
amount is the amount printed for that item.
"""


def parse_localized_amount(value: str) -> Decimal | None:
    normalized = value.replace("\u00a0", " ").strip()
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", normalized):
        normalized = normalized.replace(".", "")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def find_explicit_total_amount(text: str) -> Decimal | None:
    lines = text.splitlines()
    normalized_lines = [
        "".join(
            char
            for char in unicodedata.normalize("NFKD", line).casefold()
            if not unicodedata.combining(char)
        )
        for line in lines
    ]

    for index, normalized_line in enumerate(normalized_lines):
        match = TOTAL_LABEL.search(normalized_line)
        if not match:
            continue
        if any(
            word in normalized_line
            for word in (
                "factura curenta",
                "loc de consum",
                "consum cu tva",
                "anterior",
                "precedent",
                "restant",
            )
        ):
            continue

        following_lines = lines[index + 1:index + 9]
        equals_line = next(
            (
                offset
                for offset, line in enumerate(following_lines)
                if "=" in line
            ),
            None,
        )
        if equals_line is not None:
            candidate_lines = following_lines[equals_line + 1:]
        else:
            candidate_lines = following_lines
        for segment in candidate_lines:
            for amount_match in AMOUNT_TOKEN.finditer(segment):
                amount = parse_localized_amount(amount_match.group())
                if amount is not None:
                    return amount

        if equals_line is None:
            suffix = lines[index][match.end():]
            for amount_match in AMOUNT_TOKEN.finditer(suffix):
                amount = parse_localized_amount(amount_match.group())
                if amount is not None:
                    return amount

    return None


def find_previous_balance(text: str) -> Decimal | None:
    lines = text.splitlines()
    normalized_lines = [
        "".join(
            char
            for char in unicodedata.normalize("NFKD", line).casefold()
            if not unicodedata.combining(char)
        )
        for line in lines
    ]

    for label_pattern in PREVIOUS_BALANCE_LABELS:
        for index, normalized_line in enumerate(normalized_lines):
            match = label_pattern.search(normalized_line)
            if not match:
                continue

            suffix = lines[index][match.end():]
            following_lines = lines[index + 1:index + 9]
            candidates = [
                amount
                for segment in [*following_lines, suffix]
                for amount_match in AMOUNT_TOKEN.finditer(segment)
                if (amount := parse_localized_amount(amount_match.group())) is not None
                and amount >= 0
            ]
            if label_pattern is PREVIOUS_BALANCE_LABELS[1]:
                equals_index = next(
                    (
                        offset
                        for offset, line in enumerate(following_lines)
                        if "=" in line
                    ),
                    None,
                )
                if equals_index is not None:
                    prior_amounts = [
                        amount
                        for segment in following_lines[:equals_index]
                        for amount_match in AMOUNT_TOKEN.finditer(segment)
                        if (amount := parse_localized_amount(amount_match.group()))
                        is not None
                        and amount >= 0
                    ]
                    if len(prior_amounts) >= 2:
                        return prior_amounts[1]
            if candidates:
                return candidates[0]
    return None


def extract_invoice(text: str, pdf_content: bytes | None = None) -> GeminiInvoiceExtraction:
    if not settings.gemini_api_key:
        raise ExtractionUnavailable("Configure GEMINI_API_KEY to process invoices.")

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        contents = [invoice_extraction_prompt()]
        if text.strip():
            contents.append(f"INVOICE TEXT:\n{text}")
        elif pdf_content:
            contents.append(
                types.Part.from_bytes(data=pdf_content, mime_type="application/pdf")
            )
        else:
            raise ExtractionFailed("The invoice contains no processable data.")
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=gemini_response_schema(),
            temperature=0,
        )
        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=contents,
                    config=config,
                )
                break
            except genai_errors.ServerError as exc:
                if exc.code not in RETRYABLE_STATUS_CODES:
                    raise
                if attempt == MAX_TRANSIENT_RETRIES:
                    logger.warning(
                        "Gemini is temporarily unavailable after %d attempts (status %s)",
                        attempt + 1,
                        exc.code,
                    )
                    raise ExtractionFailed(
                        "Gemini is temporarily unavailable. Please try again in a moment.",
                        status_code=503,
                    ) from exc
                delay = 2**attempt
                logger.warning(
                    "Gemini returned status %s; retrying in %d second(s)",
                    exc.code,
                    delay,
                )
                time.sleep(delay)
        if not response.text:
            raise ExtractionFailed("Gemini returned an empty response.")
        extraction = GeminiInvoiceExtraction.model_validate_json(response.text)
        if text.strip():
            extraction_updates: dict[str, Any] = {}
            confidence_updates: dict[str, float] = {}
            explicit_total = find_explicit_total_amount(text)
            if explicit_total is not None:
                extraction_updates["total_amount"] = float(explicit_total)
                confidence_updates["total_amount"] = 0.99
            previous_balance = find_previous_balance(text)
            if previous_balance is not None:
                extraction_updates["previous_balance"] = float(previous_balance)
                confidence_updates["previous_balance"] = 0.99
            if extraction_updates:
                extraction_updates["field_confidence"] = (
                    extraction.field_confidence.model_copy(update=confidence_updates)
                )
                extraction = extraction.model_copy(update=extraction_updates)
        return extraction
    except ExtractionFailed:
        raise
    except Exception as exc:
        if isinstance(exc, genai_errors.APIError) and exc.code == 429:
            logger.warning("Gemini rate limit reached")
            raise ExtractionFailed(
                "Gemini's request limit was reached. Please try again in a moment.",
                status_code=503,
            ) from exc
        logger.exception("Gemini invoice extraction failed")
        raise ExtractionFailed("Gemini could not extract the invoice data.") from exc
