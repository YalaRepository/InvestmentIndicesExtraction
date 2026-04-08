from __future__ import annotations

from pathlib import Path

from pypdf.errors import FileNotDecryptedError

from .cashflows import extract_cashflows
from .fund_values import find_fund_value
from .models import DocumentContext
from .pdf_utils import read_pdf_pages
from .providers import build_document_context
from .utils import extract_report_date


def build_rows(pdf_path: Path | DocumentContext) -> list[dict[str, str]]:
    context = pdf_path if isinstance(pdf_path, DocumentContext) else build_document_context(pdf_path)
    provider = context.provider
    try:
        pages = read_pdf_pages(context.pdf_path)

    except FileNotDecryptedError:
        return [
            {
                "index_name": context.index_name,
                "pdf_file": context.relative_pdf_path,
                "provider": provider,
                "document_type": context.document_type,
                "report_date": "",
                "fund_value": "",
                "fund_value_status": "not_found",
                "fund_value_source": "",
                "fund_value_page": "",
                "column_headings": "",
                "cashflow_status": "not_found",
                "cashflow_date": "not found",
                "cashflow_amount": "not found",
                "cashflow_type": "not found",
                "cashflow_source": "not found",
                "status": "encrypted_pdf",
            }
        ]
    except Exception as exc:
        return [
            {
                "index_name": context.index_name,
                "pdf_file": context.relative_pdf_path,
                "provider": provider,
                "document_type": context.document_type,
                "report_date": "",
                "fund_value": "",
                "fund_value_status": "not_found",
                "fund_value_source": "",
                "fund_value_page": "",
                "column_headings": "",
                "cashflow_status": "not_found",
                "cashflow_date": "not found",
                "cashflow_amount": "not found",
                "cashflow_type": "not found",
                "cashflow_source": "not found",
                "status": f"error: {exc}",
            }
        ]

    full_text = "\n".join(pages)
    report_date = extract_report_date(full_text)
    fund_value = find_fund_value(context, pages)
    cashflows = extract_cashflows(context, pages, report_date)

    if not cashflows:
        cashflows = [
            {
                "cashflow_date": "not found",
                "cashflow_amount": "not found",
                "cashflow_type": "not found",
                "cashflow_source": "not found",
                "cashflow_status": "not_found",
            }
        ]

    rows = []
    for cashflow in cashflows:
        fund_value_found = fund_value is not None and bool(fund_value.value)
        cashflow_found = cashflow.get("cashflow_status") != "not_found"
        row_status = "ok"
        if not fund_value_found and not cashflow_found:
            row_status = "fund_value_and_cashflow_not_found"
        elif not fund_value_found:
            row_status = "fund_value_not_found"
        elif not cashflow_found:
            row_status = "cashflow_not_found"

        rows.append(
            {
                "index_name": context.index_name,
                "pdf_file": context.relative_pdf_path,
                "provider": provider,
                "document_type": context.document_type,
                "report_date": report_date,
                "fund_value": fund_value.value if fund_value else "",
                "fund_value_status": "found" if fund_value_found else "not_found",
                "fund_value_source": fund_value.source if fund_value else "",
                "fund_value_page": str(fund_value.page) if fund_value else "",
                "column_headings": fund_value.column_headings if fund_value else "",
                "cashflow_date": cashflow["cashflow_date"],
                "cashflow_amount": cashflow["cashflow_amount"],
                "cashflow_type": cashflow["cashflow_type"],
                "cashflow_source": cashflow["cashflow_source"],
                "cashflow_status": cashflow.get("cashflow_status", "found"),
                "status": row_status,
            }
        )
    return rows
