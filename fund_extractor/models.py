from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentContext:
    pdf_path: Path
    index_name: str
    relative_pdf_path: str
    provider: str
    document_type: str


@dataclass
class FundValueMatch:
    value: str
    source: str
    page: int
    column_headings: str
