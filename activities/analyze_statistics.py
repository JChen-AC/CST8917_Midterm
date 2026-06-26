import base64
from dataclasses import asdict
import io

from pypdf import PdfReader
import azure.durable_functions as df

from models import PDFStatistics


bp = df.Blueprint()


def _decode_pdf_bytes(input_data: dict) -> bytes:
    if "blob_bytes_b64" in input_data:
        return base64.b64decode(input_data["blob_bytes_b64"])

    blob_bytes = input_data.get("blob_bytes", b"")
    if isinstance(blob_bytes, str):
        return base64.b64decode(blob_bytes)

    return bytes(blob_bytes)


@bp.activity_trigger(input_name="inputData")
def analyze_statistics(inputData: dict) -> dict:
    blob_bytes = _decode_pdf_bytes(inputData)
    reader = PdfReader(io.BytesIO(blob_bytes))

    page_count = len(reader.pages)
    word_count = 0

    for page in reader.pages:
        text = page.extract_text() or ""
        word_count += len(text.split())

    avg_words_per_page = word_count / page_count if page_count else 0.0
    estimated_reading_time_min = word_count / 200.0

    statistics = PDFStatistics(
        page_count=page_count,
        word_count=word_count,
        avg_words_per_page=avg_words_per_page,
        estimated_reading_time_min=estimated_reading_time_min,
    )

    return asdict(statistics)