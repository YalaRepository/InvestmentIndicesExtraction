from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError

from .config import PDF_PASSWORDS_CSV


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



def read_pdf_pages(path: Path, password: str = "") -> list[str]:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        if not password:
            password = get_pdf_password(path)
        result = reader.decrypt(password)
        if result == 0:
            raise FileNotDecryptedError(f"{path.name} is encrypted")
    return [page.extract_text() or "" for page in reader.pages]
