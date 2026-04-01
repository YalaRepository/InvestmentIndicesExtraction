from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .config import AMOUNT_PATTERN, DATE_PATTERNS, FULL_DATE_PATTERN


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



def candidate_page_numbers(total_pages: int, preferred: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for page_number in preferred:
        if 1 <= page_number <= total_pages and page_number not in seen:
            seen.add(page_number)
            ordered.append(page_number)
    return ordered



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



def extract_report_date(text: str) -> str:
    patterns = [
        rf"\b\d{{2}} [A-Za-z]{{3,9}} \d{{4}}\s*-\s*({FULL_DATE_PATTERN[2:-2]})",
        rf"month ended\s+({FULL_DATE_PATTERN[2:-2]})",
        rf"month ending\s+({FULL_DATE_PATTERN[2:-2]})",
        rf"reporting date\s+({FULL_DATE_PATTERN[2:-2]})",
        rf"as at\s+({FULL_DATE_PATTERN[2:-2]})",
        rf"to\s+({FULL_DATE_PATTERN[2:-2]})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_date(match.group(1))
    return ""
