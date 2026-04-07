from pathlib import Path

DATA_DIR = Path("Data")
OUTPUT_CSV = Path("extracted_fund_data.csv")
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

def SetDataDir(pname):
    global DATA_DIR
    DATA_DIR = Path(pname)

def SetOutputFName(fname):
    global OUTPUT_CSV
    OUTPUT_CSV = Path(fname+"_extracted_fund_data.csv")

