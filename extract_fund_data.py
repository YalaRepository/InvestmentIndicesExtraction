from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError


DATA_DIR = Path("Data")
OUTPUT_CSV = Path("extracted_fund_data.csv")
PDF_PASSWORDS_CSV = Path("pdf_passwords.csv")


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


@dataclass
class FundValueMatch:
    value: str
    source: str
    page: int


def detect_provider(path: Path) -> str:
    name = path.name.lower()
    if "allan gray" in name:
        return "Allan Gray"
    if "agp stable" in name:
        return "AGP Stable"
    if "ijg" in name:
        return "IJG"
    if "m&g" in name or "mandg" in name:
        return "M&G"
    if "ninety one" in name:
        return "Ninety One"
    if "sanlam" in name:
        return "Sanlam"
    if "allegrow" in name:
        return "Allegrow"
    if "contributions_and_withdrawals" in name:
        return "NAM Contributions"
    if "monthly_reports" in name:
        return "NAM Monthly"
    return "Unknown"


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def parse_amount(raw: str) -> Decimal | None:
    cleaned = raw.strip()
    if not cleaned:
        return None

    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()").replace(",", "").replace(" ", "")
    if cleaned in {"", "-", "."}:
        return None

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -value if negative else value


def format_amount(raw: str) -> str:
    value = parse_amount(raw)
    if value is None:
        return ""
    return f"{value:.2f}"


def parse_date(raw: str) -> str:
    cleaned = normalize_space(raw)
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(cleaned, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def parse_date_with_report_year(raw: str, report_date: str) -> str:
    parsed = parse_date(raw)
    if parsed:
        return parsed

    cleaned = normalize_space(raw)
    if report_date:
        try:
            report_year = datetime.strptime(report_date, "%Y-%m-%d").year
        except ValueError:
            report_year = None
        if report_year is not None:
            for pattern in ("%d-%b", "%d-%B"):
                try:
                    return datetime.strptime(
                        f"{cleaned}-{report_year}",
                        f"{pattern}-%Y",
                    ).date().isoformat()
                except ValueError:
                    continue
    return ""


@lru_cache(maxsize=1)
def load_pdf_passwords() -> dict[str, str]:
    if not PDF_PASSWORDS_CSV.exists():
        return {}

    passwords: dict[str, str] = {}
    with PDF_PASSWORDS_CSV.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            filename = (row.get("pdf_file") or "").strip()
            password = (row.get("password") or "").strip()
            if filename and password:
                passwords[filename] = password
    return passwords


def get_pdf_password(path: Path) -> str:
    return load_pdf_passwords().get(path.name, "")


def extract_report_date(text: str) -> str:
    patterns = [
        rf"\b\d{{2}} [A-Za-z]{{3,9}} \d{{4}}\s*-\s*({DATE_CAPTURE_PATTERN})",
        rf"month ended\s+({DATE_CAPTURE_PATTERN})",
        rf"month ending\s+({DATE_CAPTURE_PATTERN})",
        rf"reporting date\s+({DATE_CAPTURE_PATTERN})",
        rf"as at\s+({DATE_CAPTURE_PATTERN})",
        rf"to\s+({DATE_CAPTURE_PATTERN})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_date(match.group(1))
    return ""


def read_pdf_pages(path: Path, password: str = "") -> list[str]:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        if not password:
            password = get_pdf_password(path)
        result = reader.decrypt(password)
        if result == 0:
            raise FileNotDecryptedError(f"{path.name} is encrypted")
    return [page.extract_text() or "" for page in reader.pages]


def find_fund_value(provider: str, pages: list[str]) -> FundValueMatch | None:
    provider_method = {
        "AGP Stable": fund_value_agp_stable,
        "Allan Gray": fund_value_allan_gray,
        "Allegrow": fund_value_allegrow,
        "IJG": fund_value_ijg,
        "NAM Monthly": fund_value_nam_monthly,
    }.get(provider)
    if provider_method:
        match = provider_method(pages)
        if match:
            return match

    generic = fund_value_generic(pages)
    return generic


def fund_value_generic(pages: list[str]) -> FundValueMatch | None:
    label_groups = [
        ["closing market value", "market value as at"],
        ["closing balance"],
    ]

    for labels in label_groups:
        for page_number, page_text in enumerate(pages, start=1):
            lines = [line.strip() for line in page_text.splitlines() if line.strip()]
            page_lower = page_text.lower()
            for index, line in enumerate(lines):
                lowered = normalize_space(line).lower()
                if not any(lowered.startswith(label) for label in labels):
                    continue
                if "cash account" in page_lower and "closing balance" in lowered:
                    continue
                same_line_amounts = re.findall(AMOUNT_PATTERN, line)
                if same_line_amounts:
                    return FundValueMatch(
                        value=format_amount(same_line_amounts[-1]),
                        source=line,
                        page=page_number,
                    )

                for offset in range(1, 4):
                    if index + offset >= len(lines):
                        break
                    next_line = lines[index + offset]
                    next_amounts = re.findall(AMOUNT_PATTERN, next_line)
                    if next_amounts:
                        return FundValueMatch(
                            value=format_amount(next_amounts[0]),
                            source=f"{line} | {next_line}",
                            page=page_number,
                        )
    return None


def fund_value_allan_gray(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        if "all-in market" not in page_text.lower():
            continue
        for line in page_text.splitlines():
            compact = normalize_space(line)
            if compact.lower().startswith("total "):
                amounts = re.findall(AMOUNT_PATTERN, compact)
                if len(amounts) >= 3:
                    return FundValueMatch(
                        value=format_amount(amounts[2]),
                        source=compact,
                        page=page_number,
                    )
    return None


def fund_value_agp_stable(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            if not line.lower().startswith("closing balance"):
                continue
            match = re.search(
                r"Closing Balance\s+\d[\d,]*\.\d+\s+\d[\d,]*\.\d+\s+(\d[\d,]*\.\d{2})\s+\d{2}/\d{2}/\d{4}",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                return FundValueMatch(
                    value=format_amount(match.group(1)),
                    source=line,
                    page=page_number,
                )
    return None


def fund_value_allegrow(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lowered_page = page_text.lower()
        if "per balance sheet" not in lowered_page:
            continue
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        after_header = False
        for index, line in enumerate(lines):
            if "per balance sheet" in line.lower():
                after_header = True
                continue
            if not after_header:
                continue
            if "summary of financial assets" in line.lower():
                break
            if (
                re.fullmatch(r"[\d() -]+", line)
                and index > 0
                and "other assets and liabilities" in lines[index - 1].lower()
            ):
                groups = line.replace("(", "").replace(")", "").split()
                if len(groups) >= 6 and len(groups) % 2 == 0:
                    midpoint = len(groups) // 2
                    raw_value = " ".join(groups[midpoint:])
                    return FundValueMatch(
                        value=format_amount(raw_value),
                        source=f"{lines[index - 1]} | {line}",
                        page=page_number,
                    )
            if re.fullmatch(r"[\d() -]+", line):
                parts = [part for part in re.split(r"\s{2,}", line) if part]
                if len(parts) >= 2:
                    return FundValueMatch(
                        value=format_amount(parts[-1]),
                        source=line,
                        page=page_number,
                    )
    return None


def fund_value_ijg(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            if not line.lower().startswith("indicative fair value"):
                continue
            amounts = re.findall(AMOUNT_PATTERN, line)
            if amounts:
                return FundValueMatch(
                    value=format_amount(amounts[-1]),
                    source=line,
                    page=page_number,
                )
    return None


def fund_value_nam_monthly(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lowered_page = page_text.lower()
        if "adjusted portfolio total" not in lowered_page:
            continue
        if "investment portfolio summary" not in lowered_page or "all-in market" not in lowered_page:
            continue
        compact = normalize_space(page_text)
        match = re.search(
            r"Adjusted Portfolio Total\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")",
            compact,
            flags=re.IGNORECASE,
        )
        if match:
            return FundValueMatch(
                value=format_amount(match.group(3)),
                source=normalize_space(match.group(0)),
                page=page_number,
            )
    return None


def extract_cashflows(
    provider: str, pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    provider_method = {
        "AGP Stable": cashflows_agp_stable,
        "Allan Gray": cashflows_allan_gray,
        "IJG": no_cashflows,
        "Sanlam": cashflows_sanlam,
        "NAM Contributions": cashflows_nam_contributions,
        "M&G": cashflows_m_and_g,
        "Ninety One": cashflows_ninety_one,
        "NAM Monthly": cashflows_nam_monthly,
        "Allegrow": cashflows_allegrow,
    }.get(provider)

    if provider_method:
        return dedupe_cashflows(provider_method(pages, report_date, pdf_path))

    return cashflows_generic(pages, report_date)


def no_cashflows(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    return []


def cashflows_sanlam(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    text = "\n".join(pages)
    pattern = re.compile(
        rf"({FULL_DATE_PATTERN})\s+({FULL_DATE_PATTERN})\s+([A-Za-z][A-Za-z ()/-]+?)\s+({AMOUNT_PATTERN})\s+\d[\d.]*\s+({AMOUNT_PATTERN})",
        re.IGNORECASE,
    )
    rows = []
    for match in pattern.finditer(text):
        description = normalize_space(match.group(3))
        amount = format_amount(match.group(4))
        if not amount:
            continue
        rows.append(
            {
                "cashflow_date": parse_date(match.group(1)),
                "cashflow_amount": amount,
                "cashflow_type": description,
                "cashflow_source": normalize_space(match.group(0)),
            }
        )
    return rows


def cashflows_nam_contributions(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    text = "\n".join(pages)
    sections = []
    for keyword in ("Withdrawals", "Contributions"):
        pattern = re.compile(
            rf"{keyword}\s+({FULL_DATE_PATTERN}).*?([A-Z][A-Z ()/-]+?)\s+({AMOUNT_PATTERN})\s+Total {keyword}",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(text)
        if match:
            sections.append(
                {
                    "cashflow_date": parse_date(match.group(1)),
                    "cashflow_amount": format_amount(match.group(3)),
                    "cashflow_type": keyword[:-1] if keyword.endswith("s") else keyword,
                    "cashflow_source": normalize_space(match.group(0)),
                }
            )
    return sections


def candidate_page_numbers(total_pages: int, preferred: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for page_number in preferred:
        if 1 <= page_number <= total_pages and page_number not in seen:
            seen.add(page_number)
            ordered.append(page_number)
    return ordered


def cashflows_m_and_g(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    rows = []
    seen_transaction_keys: set[tuple[str, str, str]] = set()
    preferred_pages = candidate_page_numbers(len(pages), (30, 31, 32, 33, 34, 35))

    for page_number in preferred_pages:
        page_text = pages[page_number - 1]
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if "gemlife retirement fund" not in lowered:
                continue
            if "redemption" not in lowered:
                continue

            date_matches = re.findall(r"\b\d{2}-[A-Za-z]{3,9}\b", line)
            amounts = re.findall(AMOUNT_PATTERN, line)
            if len(date_matches) < 2 or len(amounts) < 2:
                continue

            cashflow_date = parse_date_with_report_year(date_matches[1], report_date)
            cashflow_amount = format_amount(amounts[-2])
            key = (cashflow_date, cashflow_amount, "Withdrawal")
            if key in seen_transaction_keys:
                continue
            seen_transaction_keys.add(key)

            rows.append(
                {
                    "cashflow_date": cashflow_date,
                    "cashflow_amount": cashflow_amount,
                    "cashflow_type": "Withdrawal",
                    "cashflow_source": f"page {page_number}: {line}",
                }
            )

    if rows:
        return dedupe_cashflows(rows)

    for page_text in pages:
        for line in page_text.splitlines():
            compact = normalize_space(line)
            if not compact.lower().startswith("net contributions or withdrawals"):
                continue
            amounts = re.findall(AMOUNT_PATTERN, compact)
            if not amounts:
                continue
            rows.append(
                {
                    "cashflow_date": report_date,
                    "cashflow_amount": format_amount(amounts[0]),
                    "cashflow_type": "Net Contributions or Withdrawals",
                    "cashflow_source": compact,
                }
            )
    return dedupe_cashflows(rows)


def cashflows_allan_gray(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    rows = []
    pattern = re.compile(
        r"Capital contributed\s+" + AMOUNT_PATTERN + r"\s+As at\s+" + DATE_CAPTURE_PATTERN + r"\s+" + AMOUNT_PATTERN + r"\s+This month\s+(" + AMOUNT_PATTERN + r")",
        re.IGNORECASE,
    )
    for page_text in pages:
        compact = normalize_space(page_text)
        match = pattern.search(compact)
        if not match:
            continue
        rows.append(
            {
                "cashflow_date": report_date,
                "cashflow_amount": format_amount(match.group(1)),
                "cashflow_type": "Withdrawal" if parse_amount(match.group(1)) and parse_amount(match.group(1)) < 0 else "Contribution",
                "cashflow_source": normalize_space(match.group(0)),
            }
        )
    return dedupe_cashflows(rows)


def cashflows_summary_lines(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    labels = ["cash withdrawal", "cash contribution"]
    rows = []
    for page_text in pages:
        for line in page_text.splitlines():
            compact = normalize_space(line)
            lowered = compact.lower()
            if not any(label in lowered for label in labels):
                continue
            amounts = re.findall(AMOUNT_PATTERN, compact)
            if not amounts:
                continue
            rows.append(
                {
                    "cashflow_date": "",
                    "cashflow_amount": format_amount(amounts[-1]),
                    "cashflow_type": "Cash Withdrawal"
                    if "cash withdrawal" in lowered
                    else "Cash Contribution",
                    "cashflow_source": compact,
                }
            )
    return dedupe_cashflows(rows)


def cashflows_allegrow(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    if not report_date:
        return []
    report_month = report_date[:7]
    text = "\n".join(pages)
    pattern = re.compile(
        rf"({FULL_DATE_PATTERN})\s+\d+\s+Distributions of income\s+({AMOUNT_PATTERN})\s+-\s+({AMOUNT_PATTERN})",
        re.IGNORECASE,
    )
    rows = []
    for match in pattern.finditer(text):
        cashflow_date = parse_date(match.group(1))
        if not cashflow_date.startswith(report_month):
            continue
        rows.append(
            {
                "cashflow_date": cashflow_date,
                "cashflow_amount": format_amount(match.group(3)),
                "cashflow_type": "Distribution",
                "cashflow_source": normalize_space(match.group(0)),
            }
        )
    return rows


def cashflows_agp_stable(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    rows = []
    for page_text in pages:
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            if "withdrawal disinvestment" not in line.lower():
                continue
            match = re.search(
                r"(\d{2}/\d{2}/\d{4})\s+Withdrawal Disinvestment.*?\(([\d,]+\.\d{2})\)\s+\d[\d,]*\.\d{2}",
                line,
                flags=re.IGNORECASE,
            )
            if not match:
                amounts = re.findall(AMOUNT_PATTERN, line)
                if len(amounts) < 2:
                    continue
                amount = amounts[-2]
                cashflow_date = ""
            else:
                cashflow_date = parse_date(match.group(1))
                amount = f"({match.group(2)})"
            rows.append(
                {
                    "cashflow_date": cashflow_date,
                    "cashflow_amount": format_amount(amount),
                    "cashflow_type": "Withdrawal Disinvestment",
                    "cashflow_source": line,
                }
            )
    return dedupe_cashflows(rows)


def find_matching_nam_contributions_pdf(pdf_path: Path, report_date: str) -> Path | None:
    portfolio_code_match = re.search(r"_(\d{5})_", pdf_path.name)
    target_parts = ["contributions_and_withdrawals"]
    if portfolio_code_match:
        target_parts.append(portfolio_code_match.group(1))
    if report_date:
        target_parts.append(report_date)

    for candidate in DATA_DIR.glob("*.[Pp][Dd][Ff]"):
        lowered = candidate.name.lower()
        if candidate == pdf_path:
            continue
        if all(part.lower() in lowered for part in target_parts):
            return candidate
    return None


def cashflows_nam_monthly(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    if pdf_path is None:
        return []

    contributions_pdf = find_matching_nam_contributions_pdf(pdf_path, report_date)
    if contributions_pdf is None:
        return []

    contribution_pages = read_pdf_pages(contributions_pdf)
    return cashflows_nam_contributions(contribution_pages, report_date, contributions_pdf)


def cashflows_ninety_one(
    pages: list[str], report_date: str, pdf_path: Path | None = None
) -> list[dict[str, str]]:
    rows = []
    preferred_pages = candidate_page_numbers(len(pages), (15, 16))

    for page_number in preferred_pages:
        page_text = pages[page_number - 1]
        if "cash account" not in page_text.lower():
            continue

        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.upper() != "CLIENT WITHDRAWAL":
                continue

            settlement_date = parse_date(lines[index - 1]) if index >= 1 else ""
            debit = lines[index + 3] if index + 3 < len(lines) else ""
            credit = lines[index + 4] if index + 4 < len(lines) else ""
            amount_raw = ""
            if parse_amount(debit) not in (None, Decimal("0")):
                amount_raw = debit
            elif parse_amount(credit) not in (None, Decimal("0")):
                amount_raw = credit

            amount = format_amount(amount_raw)
            if not amount:
                continue

            source_parts = [
                lines[pos]
                for pos in range(max(0, index - 1), min(len(lines), index + 5))
            ]
            rows.append(
                {
                    "cashflow_date": settlement_date,
                    "cashflow_amount": amount,
                    "cashflow_type": "Client Withdrawal",
                    "cashflow_source": f"page {page_number}: {' | '.join(source_parts)}",
                }
            )

    if rows:
        return dedupe_cashflows(rows)

    for page_text in pages:
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.lower() != "cash withdrawal":
                continue
            for next_line in lines[index + 1 : index + 4]:
                if parse_amount(next_line) is None:
                    continue
                rows.append(
                    {
                        "cashflow_date": report_date,
                        "cashflow_amount": format_amount(next_line),
                        "cashflow_type": "Cash Withdrawal",
                        "cashflow_source": f"{line} | {next_line}",
                    }
                )
                break
    return dedupe_cashflows(rows)


def cashflows_generic(pages: list[str], report_date: str) -> list[dict[str, str]]:
    keywords = [
        "withdrawal",
        "contribution",
        "benefit payment",
        "drawdown",
        "distribution",
    ]
    rows = []
    for page_text in pages:
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            date_match = re.search(FULL_DATE_PATTERN, line)
            amount_match = re.search(AMOUNT_PATTERN, line)
            if not amount_match:
                continue
            rows.append(
                {
                    "cashflow_date": parse_date(date_match.group(0)) if date_match else "",
                    "cashflow_amount": format_amount(amount_match.group(0)),
                    "cashflow_type": next(
                        keyword.title()
                        for keyword in keywords
                        if keyword in lowered
                    ),
                    "cashflow_source": line,
                }
            )
    return dedupe_cashflows(rows)


def dedupe_cashflows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    unique_rows = []
    for row in rows:
        key = (row["cashflow_date"], row["cashflow_amount"], row["cashflow_source"])
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def build_rows(pdf_path: Path) -> list[dict[str, str]]:
    provider = detect_provider(pdf_path)
    try:
        pages = read_pdf_pages(pdf_path)
    except FileNotDecryptedError:
        return [
            {
                "pdf_file": pdf_path.name,
                "provider": provider,
                "report_date": "",
                "fund_value": "",
                "fund_value_source": "",
                "fund_value_page": "",
                "cashflow_date": "",
                "cashflow_amount": "",
                "cashflow_type": "",
                "cashflow_source": "",
                "status": "encrypted_pdf",
            }
        ]
    except Exception as exc:
        return [
            {
                "pdf_file": pdf_path.name,
                "provider": provider,
                "report_date": "",
                "fund_value": "",
                "fund_value_source": "",
                "fund_value_page": "",
                "cashflow_date": "",
                "cashflow_amount": "",
                "cashflow_type": "",
                "cashflow_source": "",
                "status": f"error: {exc}",
            }
        ]

    full_text = "\n".join(pages)
    report_date = extract_report_date(full_text)
    fund_value = find_fund_value(provider, pages)
    cashflows = extract_cashflows(provider, pages, report_date, pdf_path)

    if not cashflows:
        cashflows = [
            {
                "cashflow_date": "",
                "cashflow_amount": "",
                "cashflow_type": "",
                "cashflow_source": "",
            }
        ]

    rows = []
    for cashflow in cashflows:
        rows.append(
            {
                "pdf_file": pdf_path.name,
                "provider": provider,
                "report_date": report_date,
                "fund_value": fund_value.value if fund_value else "",
                "fund_value_source": fund_value.source if fund_value else "",
                "fund_value_page": str(fund_value.page) if fund_value else "",
                "cashflow_date": cashflow["cashflow_date"],
                "cashflow_amount": cashflow["cashflow_amount"],
                "cashflow_type": cashflow["cashflow_type"],
                "cashflow_source": cashflow["cashflow_source"],
                "status": "ok",
            }
        )
    return rows


def main() -> None:
    pdf_paths = sorted(DATA_DIR.glob("*.[Pp][Dd][Ff]"))
    all_rows: list[dict[str, str]] = []
    for pdf_path in pdf_paths:
        all_rows.extend(build_rows(pdf_path))

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "pdf_file",
                "provider",
                "report_date",
                "fund_value",
                "fund_value_source",
                "fund_value_page",
                "cashflow_date",
                "cashflow_amount",
                "cashflow_type",
                "cashflow_source",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
