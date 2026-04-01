from __future__ import annotations

from pathlib import Path

from pypdf.errors import FileNotDecryptedError

from .cashflows import extract_cashflows
from .fund_values import find_fund_value
from .pdf_utils import read_pdf_pages
from .providers import detect_provider
from .utils import extract_report_date



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
