import base64
from dataclasses import asdict
import io
import logging
import re

from pypdf import PdfReader
import azure.durable_functions as df

from models import SensitiveDataReport


bp = df.Blueprint()


MONTHS_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

EMAIL_PATTERN = r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
URL_PATTERN = r"\bhttps?://[^\s<>()\[\]{}\"']+"
PHONE_PATTERNS = [
    r"\b(?:\+1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b",
    r"\b\+\d{1,3}(?:[\s.-]\d{2,4}){2,4}\b",
]
DATE_PATTERNS = [
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    rf"\b{MONTHS_PATTERN}\s+\d{{1,2}},\s+\d{{4}}\b",
]


def _decode_pdf_bytes(input_data: dict) -> bytes:
    if "blob_bytes_b64" in input_data:
        return base64.b64decode(input_data["blob_bytes_b64"])

    blob_bytes = input_data.get("blob_bytes", b"")
    if isinstance(blob_bytes, str):
        return base64.b64decode(blob_bytes)

    return bytes(blob_bytes)


def _unique_matches(pattern: str, text: str, flags: int = 0) -> list[str]:
    matches = re.findall(pattern, text, flags)
    return sorted({match.strip() for match in matches if match and match.strip()})


def _looks_like_date(value: str) -> bool:
    return any(re.fullmatch(pattern, value, re.IGNORECASE) for pattern in DATE_PATTERNS)


@bp.activity_trigger(input_name="inputData")
def detect_sensitive_data(inputData: dict) -> dict:
    blob_bytes = _decode_pdf_bytes(inputData)
    reader = PdfReader(io.BytesIO(blob_bytes))

    text_chunks: list[str] = []
    for page in reader.pages:
        text_chunks.append(page.extract_text() or "")

    extracted_text = "\n".join(text_chunks)

    emails = _unique_matches(EMAIL_PATTERN, extracted_text)
    urls = _unique_matches(URL_PATTERN, extracted_text)
    phone_numbers: set[str] = set()
    for pattern in PHONE_PATTERNS:
        phone_numbers.update(_unique_matches(pattern, extracted_text))
    phone_numbers = {value for value in phone_numbers if not _looks_like_date(value)}

    dates: set[str] = set()
    for pattern in DATE_PATTERNS:
        dates.update(_unique_matches(pattern, extracted_text, re.IGNORECASE))

    report = SensitiveDataReport(
        emails=emails,
        phone_numbers=sorted(phone_numbers),
        urls=urls,
        dates=sorted(dates),
    )

    report_dict = asdict(report)
    return report_dict