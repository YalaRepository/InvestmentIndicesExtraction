from pathlib import Path

DATA_ROOT = Path("Data")
OUTPUT_DIR = Path("Results")
PDF_PASSWORDS_CSV = Path("passwords")

DATE_PATTERNS = (
    "%d %B %Y",
    "%d %b %Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
)

AMOUNT_PATTERN = r"\(?-?\d[\d, ]*(?:\.\d{2})?\)?"
DATE_CAPTURE_PATTERN = r"(?:\d{2}/\d{2}/\d{4}|\d{2}-[A-Za-z]{3}-\d{4}|\d{2} [A-Za-z]{3,9} \d{4})"
FULL_DATE_PATTERN = rf"\b{DATE_CAPTURE_PATTERN}\b"


def get_index_dir(index_name: str) -> Path:
    return DATA_ROOT / index_name


def get_output_csv(index_name: str) -> Path:
    return OUTPUT_DIR / f"{index_name}_extracted_fund_data.csv"


def get_output_xlsx(index_name: str) -> Path:
    return OUTPUT_DIR / f"{index_name}_extracted_fund_data.xlsx"


def get_summary_csv() -> Path:
    return OUTPUT_DIR / "extraction_summary.csv"


def get_summary_xlsx() -> Path:
    return OUTPUT_DIR / "extraction_summary.xlsx"

