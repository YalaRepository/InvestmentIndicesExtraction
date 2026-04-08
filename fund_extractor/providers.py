from __future__ import annotations

from pathlib import Path

from .config import DATA_ROOT
from .models import DocumentContext


def detect_provider(path: Path) -> str:
    name = path.name.lower()

    if "allan gray" in name:
        return "Allan Gray"
    if any(token in name for token in ("agp stable", "agp smooth", "core growth", "cgp ")):
        return "AGP"
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
    if "(nam)" in name and "monthly statement" in name:
        return "NAM Statement"
    if "cam" in name or "investment statement_" in name:
        return "CAM"
    if "(om)" in name or "old mutual" in name:
        return "OM"
    if "stimulus" in name:
        return "Stimulus"
    if "unlisted debt" in name:
        return "Unlisted Debt"

    return "Unknown"


def detect_document_type(path: Path, provider: str) -> str:
    name = path.name.lower()

    if provider == "Allegrow" and "distribution" in name:
        return "allegrow_distribution"
    if provider == "M&G" and "monthlyreport" in name:
        return "m_and_g_monthly_report"
    if provider == "M&G":
        return "m_and_g_statement"
    if provider == "Allan Gray" and "accounts" in name:
        return "allan_gray_account"
    if provider == "Allan Gray":
        return "allan_gray_statement"
    if provider == "Ninety One" and "investment statement" in name:
        return "ninety_one_statement"
    if provider == "Ninety One":
        return "ninety_one_monthly"
    if provider == "Sanlam" and "statement m" in name:
        return "sanlam_statement_m"
    if provider == "Sanlam":
        return "sanlam_bonus"
    if provider == "OM":
        return "old_mutual_monthly"
    if provider == "Unlisted Debt":
        return "unlisted_debt_statement"
    if provider == "Stimulus":
        return "stimulus_monthend"
    if provider == "NAM Statement":
        return "nam_orion_statement"

    return provider.lower().replace(" ", "_")


def build_document_context(pdf_path: Path) -> DocumentContext:
    relative_path = pdf_path.relative_to(DATA_ROOT)
    index_name = relative_path.parts[0]
    provider = detect_provider(pdf_path)
    document_type = detect_document_type(pdf_path, provider)
    return DocumentContext(
        pdf_path=pdf_path,
        index_name=index_name,
        relative_pdf_path=relative_path.as_posix(),
        provider=provider,
        document_type=document_type,
    )
