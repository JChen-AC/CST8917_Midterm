from dataclasses import dataclass


@dataclass
class PDFStatistics:
    page_count: int
    word_count: int
    avg_words_per_page: float
    estimated_reading_time_min: float


@dataclass
class SensitiveDataReport:
    emails: list[str]
    phone_numbers: list[str]
    urls: list[str]
    dates: list[str]