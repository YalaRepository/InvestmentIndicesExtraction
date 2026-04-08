from __future__ import annotations

import re

from .config import AMOUNT_PATTERN, FULL_DATE_PATTERN
from .models import DocumentContext, FundValueMatch
from .utils import format_amount, normalize_space, parse_amount


def find_fund_value(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    provider_method = {
        "AGP": fund_value_agp,
        "Allan Gray": fund_value_allan_gray,
        "Allegrow": fund_value_allegrow,
        "CAM": fund_value_cam,
        "IJG": fund_value_ijg,
        "M&G": fund_value_m_and_g,
        "NAM Monthly": fund_value_nam_monthly,
        "NAM Statement": fund_value_nam_statement,
        "Ninety One": fund_value_ninety_one,
        "OM": fund_value_old_mutual,
        "Sanlam": fund_value_sanlam,
        "Stimulus": fund_value_stimulus,
        "Unlisted Debt": fund_value_unlisted_debt,
    }.get(context.provider)

    if provider_method:
        match = provider_method(context, pages)
        if match:
            return match

    return fund_value_generic(context, pages)


def _join_cells(cells: list[str]) -> str:
    cleaned = [normalize_space(cell) for cell in cells if normalize_space(cell)]
    return "; ".join(cleaned)


def _split_on_wide_gaps(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?:\t+|\s{2,})", text.strip()) if part.strip()]


def _format_value_row(text: str) -> str:
    raw = text.strip()
    if not raw:
        return ""

    wide_gap_parts = _split_on_wide_gaps(raw)
    if len(wide_gap_parts) > 1:
        return _join_cells(wide_gap_parts)

    token_pattern = re.compile(
        r"\d{2}/\d{2}/\d{4}"
        r"|\d{2}-[A-Za-z]{3,9}-\d{4}"
        r"|\d{2} [A-Za-z]{3,9} \d{4}"
        r"|\(?-?\d[\d,]*(?:\.\d+)?\)?%?"
    )

    matches = list(token_pattern.finditer(raw))
    if not matches:
        return normalize_space(raw)

    cells: list[str] = []
    prefix = raw[: matches[0].start()].strip()
    if prefix:
        cells.append(prefix)

    for match in matches:
        cells.append(match.group(0))

    return _join_cells(cells)


def _format_heading_row(text: str) -> str:
    raw = text.strip()
    if not raw:
        return ""

    wide_gap_parts = _split_on_wide_gaps(raw)
    if len(wide_gap_parts) > 1:
        return _join_cells(wide_gap_parts)

    return normalize_space(raw)


def _is_heading_candidate(text: str) -> bool:
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
        "price per unit",
        "number of units",
        "gross monthly return",
        "financial transaction",
        "month",
        "net amount",
        "asset value",
    ]

    return any(keyword in lowered for keyword in heading_keywords)


def _find_column_headings(lines: list[str], match_index: int) -> str:
    heading_lines: list[str] = []

    for offset in range(1, 7):
        idx = match_index - offset
        if idx < 0:
            break

        candidate = lines[idx].strip()
        if not candidate:
            continue

        if _is_heading_candidate(candidate):
            heading_lines.append(_format_heading_row(candidate))
            continue

        if heading_lines:
            break

    if not heading_lines:
        return ""

    heading_lines.reverse()
    return _join_cells(heading_lines)


def _best_amount(raw_amounts: list[str], *, strategy: str = "largest") -> str:
    parsed = []
    for raw in raw_amounts:
        value = parse_amount(raw)
        if value is None:
            continue
        parsed.append((raw, value))

    if not parsed:
        return ""

    if strategy == "first":
        return format_amount(parsed[0][0])
    if strategy == "last":
        return format_amount(parsed[-1][0])
    if strategy == "third" and len(parsed) >= 3:
        return format_amount(parsed[2][0])

    best_raw, _ = max(parsed, key=lambda item: abs(item[1]))
    return format_amount(best_raw)


def _match_from_line(
    lines: list[str],
    index: int,
    page_number: int,
    *,
    value: str,
) -> FundValueMatch | None:
    if not value:
        return None

    return FundValueMatch(
        value=value,
        source=_format_value_row(lines[index]),
        page=page_number,
        column_headings=_find_column_headings(lines, index),
    )


def fund_value_generic(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    label_groups = [
        ["closing market value", "market value as at", "total portfolio value", "indicative fair value"],
        ["closing balance"],
        ["total investment"],
    ]

    for labels in label_groups:
        for page_number, page_text in enumerate(pages, start=1):
            lines = [line.strip() for line in page_text.splitlines() if line.strip()]
            page_lower = page_text.lower()

            for index, line in enumerate(lines):
                compact_line = normalize_space(line)
                lowered = compact_line.lower()

                if not any(label in lowered for label in labels):
                    continue

                if "cash account" in page_lower and "closing balance" in lowered:
                    continue

                same_line_amounts = re.findall(AMOUNT_PATTERN, line)
                if same_line_amounts:
                    match = _match_from_line(
                        lines,
                        index,
                        page_number,
                        value=_best_amount(same_line_amounts),
                    )
                    if match:
                        return match

                for offset in range(1, 4):
                    if index + offset >= len(lines):
                        break

                    next_line = lines[index + offset].strip()
                    next_amounts = re.findall(AMOUNT_PATTERN, next_line)
                    if not next_amounts:
                        continue

                    value = _best_amount(next_amounts)
                    if not value:
                        continue

                    return FundValueMatch(
                        value=value,
                        source=_join_cells([_format_value_row(line), _format_value_row(next_line)]),
                        page=page_number,
                        column_headings=_find_column_headings(lines, index),
                    )
    return None


def fund_value_allan_gray(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        if "all-in market" not in page_text.lower():
            continue

        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            compact_line = normalize_space(line).lower()
            if not (
                compact_line.startswith("total ")
                or compact_line == "total"
                or compact_line.startswith("balance ")
                or compact_line == "balance"
            ):
                continue

            amounts = re.findall(AMOUNT_PATTERN, line)
            value = _best_amount(amounts, strategy="third") or _best_amount(amounts)
            match = _match_from_line(lines, index, page_number, value=value)
            if match:
                return match
    return None


def fund_value_agp(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            compact_line = normalize_space(line).lower()
            if not compact_line.startswith("closing balance"):
                continue

            normalized_line = normalize_space(line)
            match = re.search(
                r"Closing Balance\s+\d[\d,]*\.\d+\s+\d[\d,]*\.\d+\s+(\d[\d,]*\.\d{2})\s+\d{2}/\d{2}/\d{4}",
                normalized_line,
                flags=re.IGNORECASE,
            )
            value = format_amount(match.group(1)) if match else ""
            if not value:
                amounts = re.findall(AMOUNT_PATTERN, line)
                value = _best_amount(amounts, strategy="third") or _best_amount(amounts)
            match = _match_from_line(lines, index, page_number, value=value)
            if match:
                return match
    return None


def fund_value_allegrow(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        in_balance_sheet_section = False

        for index, line in enumerate(lines):
            lowered = normalize_space(line).lower()
            if "per balance sheet" in lowered:
                in_balance_sheet_section = True
                continue

            if not in_balance_sheet_section:
                continue

            if "summary of financial assets" in lowered:
                break

            if "other assets and liabilities" in lowered:
                for offset in range(1, 4):
                    if index + offset >= len(lines):
                        break
                    next_line = normalize_space(lines[index + offset])
                    if not re.fullmatch(r"[\d,(). -]+", next_line):
                        continue
                    parts = next_line.split()
                    if len(parts) >= 4 and len(parts) % 2 == 0:
                        midpoint = len(parts) // 2
                        first_value = " ".join(parts[:midpoint])
                        second_value = " ".join(parts[midpoint:])
                        return FundValueMatch(
                            value=format_amount(second_value),
                            source=_join_cells(
                                [
                                    "Total equity and liabilities",
                                    format_amount(first_value),
                                    format_amount(second_value),
                                ]
                            ),
                            page=page_number,
                            column_headings="Per Balance Sheet (N$); Investor's share (N$)",
                        )

    return None


def fund_value_cam(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        if "closing market value" not in page_text.lower():
            continue

        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lowered = normalize_space(line).lower()
            if not lowered.startswith("total"):
                continue

            amounts = re.findall(AMOUNT_PATTERN, line)
            value = _best_amount(amounts)
            match = _match_from_line(lines, index, page_number, value=value)
            if match:
                return match
    return None


def fund_value_ijg(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            compact = normalize_space(line)
            if index < len(lines) // 2:
                continue
            if re.fullmatch(FULL_DATE_PATTERN, compact) is None:
                continue

            for look_ahead in range(index + 1, min(len(lines), index + 6)):
                candidate = normalize_space(lines[look_ahead])
                if parse_amount(candidate) is None:
                    continue
                if re.search(r"[A-Za-z]", candidate):
                    continue
                return FundValueMatch(
                    value=format_amount(candidate),
                    source=_join_cells(
                        [
                            "Indicative Fair Value (N$)*",
                            _format_value_row(compact),
                            _format_value_row(candidate),
                        ]
                    ),
                    page=page_number,
                    column_headings="Indicative Fair Value (N$)*",
                )
    return None


def fund_value_m_and_g(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    target_labels = ["closing market value"]

    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lowered = normalize_space(line).lower()
            if not any(label in lowered for label in target_labels):
                continue

            amounts = re.findall(AMOUNT_PATTERN, line)
            if amounts:
                match = _match_from_line(lines, index, page_number, value=_best_amount(amounts))
                if match:
                    return match

            for offset in range(1, 3):
                if index + offset >= len(lines):
                    break
                next_line = lines[index + offset]
                next_amounts = re.findall(AMOUNT_PATTERN, next_line)
                if not next_amounts:
                    continue
                return FundValueMatch(
                    value=_best_amount(next_amounts),
                    source=_join_cells([_format_value_row(line), _format_value_row(next_line)]),
                    page=page_number,
                    column_headings=_find_column_headings(lines, index),
                )
    return None


def fund_value_nam_monthly(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lowered_page = page_text.lower()
        if "adjusted portfolio total" not in lowered_page:
            continue

        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if "adjusted portfolio total" not in normalize_space(line).lower():
                continue

            values_after_label: list[str] = []
            for next_line in lines[index + 1 : index + 8]:
                compact = normalize_space(next_line)
                amounts = re.findall(AMOUNT_PATTERN, compact)
                if len(amounts) == 1 and compact == amounts[0]:
                    values_after_label.append(amounts[0])
                elif values_after_label:
                    break

            value = _best_amount(values_after_label) if values_after_label else ""
            if value:
                return FundValueMatch(
                    value=value,
                    source=_join_cells([_format_value_row(line)] + [_format_value_row(v) for v in values_after_label]),
                    page=page_number,
                    column_headings=_find_column_headings(lines, index),
                )
    return None


def fund_value_nam_statement(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        if "market value" not in page_text.lower():
            continue

        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lowered = normalize_space(line).lower()
            if not lowered.startswith("total"):
                continue

            amounts = re.findall(AMOUNT_PATTERN, line)
            value = _best_amount(amounts)
            match = _match_from_line(lines, index, page_number, value=value)
            if match:
                return match
    return None


def fund_value_ninety_one(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        page_lower = page_text.lower()

        for index, line in enumerate(lines):
            lowered = normalize_space(line).lower()
            if "closing market value" in lowered:
                amounts = re.findall(AMOUNT_PATTERN, line)
                if amounts:
                    match = _match_from_line(lines, index, page_number, value=_best_amount(amounts))
                    if match:
                        return match

            if "market value" in page_lower and lowered.startswith("total"):
                amounts = re.findall(AMOUNT_PATTERN, line)
                match = _match_from_line(lines, index, page_number, value=_best_amount(amounts))
                if match:
                    return match
    return None


def fund_value_old_mutual(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    return fund_value_generic(context, pages)


def fund_value_sanlam(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    target_labels = ["closing balance", "total investment"]

    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            lowered = normalize_space(line).lower()
            if not any(label in lowered for label in target_labels):
                continue

            amounts = re.findall(AMOUNT_PATTERN, line)
            match = _match_from_line(lines, index, page_number, value=_best_amount(amounts))
            if match:
                return match
    return None


def fund_value_stimulus(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    return fund_value_generic(context, pages)


def fund_value_unlisted_debt(context: DocumentContext, pages: list[str]) -> FundValueMatch | None:
    return fund_value_generic(context, pages)
