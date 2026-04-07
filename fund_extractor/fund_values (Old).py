from __future__ import annotations

import re

from .config import AMOUNT_PATTERN
from .models import FundValueMatch
from .utils import format_amount, normalize_space


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

    return fund_value_generic(pages)


def _is_heading_candidate(text: str) -> bool:
    """
    Heuristic for identifying likely table heading rows.
    We want rows that look like labels/headers, not value rows.
    """
    compact = normalize_space(text)
    lowered = compact.lower()

    if not compact:
        return False

    if any(ch.isdigit() for ch in compact):
        return False

    heading_keywords = [
        "opening",
        "closing",
        "balance",
        "market value",
        "value",
        "assets",
        "liabilities",
        "total",
        "investment",
        "cash",
        "income",
        "capital",
        "portfolio",
        "adjusted portfolio total",
        "indicative fair value",
        "all-in market",
        "summary",
    ]

    return any(keyword in lowered for keyword in heading_keywords)


def _find_column_headings(lines: list[str], match_index: int) -> str:
    """
    Look upward from the matched row to find the most likely table heading row(s).
    Returns a compact string of one or more heading lines.
    """
    heading_lines: list[str] = []

    # Look up to 6 lines above the matched row
    for offset in range(1, 7):
        idx = match_index - offset
        if idx < 0:
            break

        candidate = normalize_space(lines[idx])
        if not candidate:
            continue

        if _is_heading_candidate(candidate):
            heading_lines.append(candidate)
            continue

        # Once we've started collecting headings, stop when we hit a non-heading line
        if heading_lines:
            break

    if not heading_lines:
        return ""

    heading_lines.reverse()
    return " | ".join(heading_lines)


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
                compact_line = normalize_space(line)
                lowered = compact_line.lower()

                if not any(lowered.startswith(label) for label in labels):
                    continue

                if "cash account" in page_lower and "closing balance" in lowered:
                    continue

                column_headings = _find_column_headings(lines, index)

                same_line_amounts = re.findall(AMOUNT_PATTERN, line)
                if same_line_amounts:
                    return FundValueMatch(
                        value=format_amount(same_line_amounts[-1]),
                        source=compact_line,
                        page=page_number,
                        column_headings=column_headings,
                    )

                for offset in range(1, 4):
                    if index + offset >= len(lines):
                        break
                    next_line = normalize_space(lines[index + offset])
                    next_amounts = re.findall(AMOUNT_PATTERN, next_line)
                    if next_amounts:
                        return FundValueMatch(
                            value=format_amount(next_amounts[0]),
                            source=f"{compact_line} | {next_line}",
                            page=page_number,
                            column_headings=column_headings,
                        )
    return None


def fund_value_allan_gray(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        if "all-in market" not in page_text.lower():
            continue

        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]

        for index, line in enumerate(lines):
            if not line.lower().startswith("total "):
                continue

            amounts = re.findall(AMOUNT_PATTERN, line)
            if len(amounts) >= 3:
                return FundValueMatch(
                    value=format_amount(amounts[2]),
                    source=line,
                    page=page_number,
                    column_headings=_find_column_headings(lines, index),
                )
    return None


def fund_value_agp_stable(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]

        for index, line in enumerate(lines):
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
                    column_headings=_find_column_headings(lines, index),
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
                        column_headings=_find_column_headings(lines, index - 1),
                    )

            if re.fullmatch(r"[\d() -]+", line):
                parts = [part for part in re.split(r"\s{2,}", line) if part]
                if len(parts) >= 2:
                    return FundValueMatch(
                        value=format_amount(parts[-1]),
                        source=line,
                        page=page_number,
                        column_headings=_find_column_headings(lines, index),
                    )
    return None


def fund_value_ijg(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]

        for index, line in enumerate(lines):
            if not line.lower().startswith("indicative fair value"):
                continue

            amounts = re.findall(AMOUNT_PATTERN, line)
            if amounts:
                return FundValueMatch(
                    value=format_amount(amounts[-1]),
                    source=line,
                    page=page_number,
                    column_headings=_find_column_headings(lines, index),
                )
    return None


def fund_value_nam_monthly(pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lowered_page = page_text.lower()
        if "adjusted portfolio total" not in lowered_page:
            continue
        if "investment portfolio summary" not in lowered_page or "all-in market" not in lowered_page:
            continue

        lines = [normalize_space(line) for line in page_text.splitlines() if line.strip()]
        compact = normalize_space(page_text)

        match = re.search(
            r"Adjusted Portfolio Total\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")\s+(" + AMOUNT_PATTERN + r")",
            compact,
            flags=re.IGNORECASE,
        )
        if match:
            heading_index = 0
            for idx, line in enumerate(lines):
                if "adjusted portfolio total" in line.lower():
                    heading_index = idx
                    break

            return FundValueMatch(
                value=format_amount(match.group(3)),
                source=normalize_space(match.group(0)),
                page=page_number,
                column_headings=_find_column_headings(lines, heading_index),
            )
    return None