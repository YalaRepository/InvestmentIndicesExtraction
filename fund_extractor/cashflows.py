from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from .config import AMOUNT_PATTERN, DATA_DIR, DATE_CAPTURE_PATTERN, FULL_DATE_PATTERN
from .pdf_utils import read_pdf_pages
from .utils import (
    candidate_page_numbers,
    dedupe_cashflows,
    format_amount,
    normalize_space,
    parse_amount,
    parse_date,
    parse_date_with_report_year,
)



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
        amount_value = parse_amount(match.group(1))
        rows.append(
            {
                "cashflow_date": report_date,
                "cashflow_amount": format_amount(match.group(1)),
                "cashflow_type": "Withdrawal" if amount_value and amount_value < 0 else "Contribution",
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
