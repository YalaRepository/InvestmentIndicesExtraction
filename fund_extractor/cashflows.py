from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from .config import AMOUNT_PATTERN, DATA_ROOT, FULL_DATE_PATTERN
from .models import DocumentContext
from .pdf_utils import read_pdf_pages
from .utils import (
    dedupe_cashflows,
    format_amount,
    normalize_space,
    parse_amount,
    parse_date,
    parse_date_with_report_year,
)


def extract_cashflows(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    provider_method = {
        "AGP": cashflows_agp,
        "Allan Gray": cashflows_allan_gray,
        "Allegrow": cashflows_allegrow,
        "CAM": cashflows_cam,
        "IJG": cashflows_ijg,
        "M&G": cashflows_m_and_g,
        "NAM Contributions": cashflows_nam_contributions,
        "NAM Monthly": cashflows_nam_monthly,
        "NAM Statement": cashflows_nam_statement,
        "Ninety One": cashflows_ninety_one,
        "OM": cashflows_old_mutual,
        "Sanlam": cashflows_sanlam,
        "Stimulus": no_cashflows,
        "Unlisted Debt": cashflows_unlisted_debt,
    }.get(context.provider)

    if provider_method:
        return dedupe_cashflows(provider_method(context, pages, report_date))

    return cashflows_generic(context, pages, report_date)


def no_cashflows(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    return []


def _amounts_from_line(line: str) -> list[str]:
    return re.findall(AMOUNT_PATTERN, line)


def _transaction_type_from_keywords(line: str, mapping: dict[str, str]) -> str:
    lowered = normalize_space(line).lower()
    for keyword, label in mapping.items():
        if keyword in lowered:
            return label
    return ""


def _row_amount(line: str, *, prefer: str = "last_non_zero") -> str:
    parsed = []
    for raw in _amounts_from_line(line):
        value = parse_amount(raw)
        if value is None:
            continue
        parsed.append((raw, value))

    if not parsed:
        return ""

    if prefer == "first":
        return format_amount(parsed[0][0])
    if prefer == "last":
        return format_amount(parsed[-1][0])

    non_zero = [item for item in parsed if item[1] != 0]
    if non_zero:
        return format_amount(non_zero[-1][0])
    return format_amount(parsed[-1][0])


def _line_cashflows(
    pages: list[str],
    *,
    keywords: dict[str, str],
    extra_required_terms: tuple[str, ...] = (),
    date_mode: str = "full",
    amount_preference: str = "last_non_zero",
    page_window: range | None = None,
    report_date: str = "",
) -> list[dict[str, str]]:
    rows = []
    iterable = enumerate(pages, start=1)

    for page_number, page_text in iterable:
        if page_window is not None and page_number not in page_window:
            continue

        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            cashflow_type = _transaction_type_from_keywords(line, keywords)
            if not cashflow_type:
                continue
            if extra_required_terms and not all(term.lower() in line.lower() for term in extra_required_terms):
                continue

            if date_mode == "short":
                date_match = re.search(r"\b\d{2}-[A-Za-z]{3,9}\b", line)
                cashflow_date = parse_date_with_report_year(date_match.group(0), report_date) if date_match else report_date
            elif date_mode == "report":
                cashflow_date = report_date
            else:
                date_match = re.search(FULL_DATE_PATTERN, line)
                cashflow_date = parse_date(date_match.group(0)) if date_match else report_date

            amount = _row_amount(line, prefer=amount_preference)
            if not amount:
                continue

            rows.append(
                {
                    "cashflow_date": cashflow_date,
                    "cashflow_amount": amount,
                    "cashflow_type": cashflow_type,
                    "cashflow_source": f"page {page_number}: {line}",
                    "cashflow_status": "found",
                }
            )
    return rows


def cashflows_sanlam(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    rows = []
    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.lower() != "order sell (benefit payment)":
                continue
            if index < 2 or index + 1 >= len(lines):
                continue

            rows.append(
                {
                    "cashflow_date": parse_date(lines[index - 2]),
                    "cashflow_amount": format_amount(lines[index + 1]),
                    "cashflow_type": "Withdrawal",
                    "cashflow_source": f"page {page_number}: {' | '.join(lines[max(0, index - 2): min(len(lines), index + 4)])}",
                    "cashflow_status": "found",
                }
            )
    return rows


def cashflows_nam_contributions(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    rows = []

    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lowered = line.lower()
            if "participant withdrawal" not in lowered and "participant contribution" not in lowered and "contribution" not in lowered and "withdrawal" not in lowered:
                continue

            if "total withdrawals" in lowered or "total contributions" in lowered:
                continue

            amount = ""
            for next_line in lines[index + 1 : index + 4]:
                if parse_amount(next_line) is not None:
                    amount = format_amount(next_line)
                    break
            if not amount:
                continue

            dates_before = [parse_date(candidate) for candidate in lines[max(0, index - 6) : index] if parse_date(candidate)]
            if not dates_before:
                continue

            rows.append(
                {
                    "cashflow_date": dates_before[-1],
                    "cashflow_amount": amount,
                    "cashflow_type": "Withdrawal" if "withdrawal" in lowered else "Contribution",
                    "cashflow_source": f"page {page_number}: {' | '.join(lines[max(0, index - 2): min(len(lines), index + 4)])}",
                    "cashflow_status": "found",
                }
            )

    return rows


def cashflows_m_and_g(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    if context.document_type == "m_and_g_statement":
        return _line_cashflows(
            pages,
            keywords={
                "purchase": "Contribution",
                "redemption": "Withdrawal",
            },
            report_date=report_date,
        )

    rows = []
    fund_terms = {
        "Gemlife": "gemlife retirement fund",
        "Namwater": "namwater retirement fund",
        "UNIPOL": "universities retirement fund",
    }
    security_name = fund_terms.get(context.index_name, "")

    for page_number, page_text in enumerate(pages, start=1):
        if page_number < 24 or page_number > 33:
            continue

        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if security_name and security_name not in lowered:
                continue

            cashflow_type = _transaction_type_from_keywords(
                line,
                {
                    "redemption": "Withdrawal",
                    "purchase": "Contribution",
                    "contribution": "Contribution",
                    "withdrawal": "Withdrawal",
                },
            )
            if not cashflow_type:
                continue

            date_match = re.search(r"\b\d{2}-[A-Za-z]{3,9}\b", line)
            if not date_match:
                continue

            amount = _row_amount(line)
            if not amount:
                continue

            rows.append(
                {
                    "cashflow_date": parse_date_with_report_year(date_match.group(0), report_date),
                    "cashflow_amount": amount,
                    "cashflow_type": cashflow_type,
                    "cashflow_source": f"page {page_number}: {line}",
                    "cashflow_status": "found",
                }
            )

    seen_keys: set[tuple[str, str, str]] = set()
    unique_rows = []
    for row in rows:
        key = (row["cashflow_date"], row["cashflow_amount"], row["cashflow_type"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_rows.append(row)

    return unique_rows


def cashflows_allan_gray(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    if context.document_type != "allan_gray_account":
        return _line_cashflows(
            pages,
            keywords={
                "deposit": "Contribution",
                "subscription": "Contribution",
                "purchase": "Contribution",
                "withdrawal": "Withdrawal",
                "redemption": "Withdrawal",
            },
            report_date=report_date,
        )

    rows = []
    pattern = re.compile(
        rf"({FULL_DATE_PATTERN})\s+(Deposit|Withdrawal)\s+\S+\s+NA Dollar CAPITAL ACCOUNT\s+({AMOUNT_PATTERN})",
        flags=re.IGNORECASE,
    )

    for page_number, page_text in enumerate(pages, start=1):
        for raw_line in page_text.splitlines():
            line = normalize_space(raw_line)
            match = pattern.search(line)
            if not match:
                continue

            rows.append(
                {
                    "cashflow_date": parse_date(match.group(1)),
                    "cashflow_amount": format_amount(match.group(3)),
                    "cashflow_type": "Contribution" if match.group(2).lower() == "deposit" else "Withdrawal",
                    "cashflow_source": f"page {page_number}: {line}",
                    "cashflow_status": "found",
                }
            )

    if rows:
        return rows

    pattern = re.compile(
        r"Capital contributed\s+" + AMOUNT_PATTERN + r"\s+As at\s+"
        + FULL_DATE_PATTERN
        + r"\s+" + AMOUNT_PATTERN + r"\s+This month\s+(" + AMOUNT_PATTERN + r")",
        re.IGNORECASE,
    )

    fallback_rows = []
    for page_number, page_text in enumerate(pages, start=1):
        compact = normalize_space(page_text)
        match = pattern.search(compact)
        if not match:
            continue

        amount_value = parse_amount(match.group(1))
        fallback_rows.append(
            {
                "cashflow_date": report_date,
                "cashflow_amount": format_amount(match.group(1)),
                "cashflow_type": "Withdrawal" if amount_value and amount_value < 0 else "Contribution",
                "cashflow_source": f"page {page_number}: {normalize_space(match.group(0))}",
                "cashflow_status": "found",
            }
        )

    return fallback_rows


def cashflows_allegrow(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    if context.document_type == "allegrow_distribution":
        rows = _line_cashflows(
            pages,
            keywords={"distributions of income": "Distribution"},
            report_date=report_date,
        )
        return rows

    return []


def cashflows_agp(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    rows = []

    allowed = {
        "withdrawal disinvestment": "Withdrawal",
        "withdrawal disinvestments": "Withdrawal",
        "lumpsum contributions": "Contribution",
        "recurring contribution": "Contribution",
    }

    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]

        for line in lines:
            if not re.match(r"\d{2}/\d{2}/\d{4}", line):
                continue

            cashflow_type = _transaction_type_from_keywords(line, allowed)
            if not cashflow_type:
                continue

            date_match = re.search(r"\d{2}/\d{2}/\d{4}", line)
            amounts = _amounts_from_line(line)
            amount = format_amount(amounts[-2]) if len(amounts) >= 2 else _row_amount(line)
            if not date_match or not amount:
                continue

            rows.append(
                {
                    "cashflow_date": parse_date(date_match.group(0)),
                    "cashflow_amount": amount,
                    "cashflow_type": cashflow_type,
                    "cashflow_source": f"page {page_number}: {line}",
                    "cashflow_status": "found",
                }
            )

    return rows


def _find_matching_pdf(context: DocumentContext, report_date: str, provider: str) -> Path | None:
    index_dir = DATA_ROOT / context.index_name
    for candidate in index_dir.rglob("*.[Pp][Dd][Ff]"):
        if candidate == context.pdf_path:
            continue
        candidate_context = candidate.name.lower()
        if provider == "NAM Contributions" and "contributions_and_withdrawals" in candidate_context:
            return candidate
    return None


def cashflows_nam_monthly(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    contributions_pdf = _find_matching_pdf(context, report_date, "NAM Contributions")
    if contributions_pdf is not None:
        contribution_pages = read_pdf_pages(contributions_pdf)
        contribution_context = DocumentContext(
            pdf_path=contributions_pdf,
            index_name=context.index_name,
            relative_pdf_path=contributions_pdf.relative_to(DATA_ROOT).as_posix(),
            provider="NAM Contributions",
            document_type="nam_contributions",
        )
        rows = cashflows_nam_contributions(contribution_context, contribution_pages, report_date)
        if rows:
            return rows

    return cashflows_generic(context, pages, report_date)


def cashflows_nam_statement(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    return _line_cashflows(
        pages,
        keywords={"contribution": "Contribution"},
        report_date=report_date,
    )


def cashflows_ninety_one(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    if context.document_type == "ninety_one_statement":
        return _line_cashflows(
            pages,
            keywords={
                "redemption": "Withdrawal",
                "purchase": "Contribution",
            },
            report_date=report_date,
        )

    rows = []

    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lowered = line.lower()
            if line.upper() not in {"CLIENT WITHDRAWAL", "CLIENT DEPOSIT"}:
                continue
            if index + 4 >= len(lines):
                continue

            if "standard bank namibia nad capital settlement account" not in lines[index + 2].lower():
                continue

            dates_before = [parse_date(candidate) for candidate in lines[max(0, index - 3): index] if parse_date(candidate)]
            settlement_date = dates_before[-1] if dates_before else report_date

            debit = lines[index + 3]
            credit = lines[index + 4]
            amount_raw = debit if parse_amount(debit) not in (None, Decimal("0")) else credit
            amount = format_amount(amount_raw)
            if not amount:
                continue

            cashflow_type = "Contribution" if "deposit" in lowered else "Withdrawal"
            rows.append(
                {
                    "cashflow_date": settlement_date,
                    "cashflow_amount": amount,
                    "cashflow_type": cashflow_type,
                    "cashflow_source": f"page {page_number}: {' | '.join(lines[max(0, index - 2): min(len(lines), index + 6)])}",
                    "cashflow_status": "found",
                }
            )

    return rows


def cashflows_cam(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    return _line_cashflows(
        pages,
        keywords={
            "purchase": "Contribution",
            "redemption": "Withdrawal",
        },
        report_date=report_date,
    )


def cashflows_ijg(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    return _line_cashflows(
        pages,
        keywords={
            "drawdown": "Drawdown",
            "contribution": "Contribution",
        },
        report_date=report_date,
    )


def cashflows_old_mutual(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    return _line_cashflows(
        pages,
        keywords={
            "disinv m/fund": "Withdrawal",
            "contrib m/fund": "Contribution",
        },
        report_date=report_date,
    )


def cashflows_unlisted_debt(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    rows = []
    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if "contributions" not in lowered and "distributions" not in lowered:
                continue

            amount = _row_amount(line)
            if not amount:
                continue

            rows.append(
                {
                    "cashflow_date": report_date,
                    "cashflow_amount": amount,
                    "cashflow_type": "Contribution" if "contributions" in lowered else "Distribution",
                    "cashflow_source": f"page {page_number}: {line}",
                    "cashflow_status": "found",
                }
            )
    return rows


def cashflows_generic(
    context: DocumentContext,
    pages: list[str],
    report_date: str,
) -> list[dict[str, str]]:
    keywords = {
        "withdrawal": "Withdrawal",
        "contribution": "Contribution",
        "benefit payment": "Withdrawal",
        "drawdown": "Drawdown",
        "distribution": "Distribution",
        "purchase": "Contribution",
        "redemption": "Withdrawal",
    }
    return _line_cashflows(pages, keywords=keywords, report_date=report_date)
