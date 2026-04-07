from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError

from .config import PDF_PASSWORDS_CSV


@lru_cache(maxsize=1)
def load_password_rows() -> list[dict[str, str]]:
    """
    Reads password file (no extension) as CSV.

    Expected structure:
        pdf_file,password

    pdf_file can be blank for generic passwords.
    """
    if not PDF_PASSWORDS_CSV.exists():
        return []

    rows: list[dict[str, str]] = []

    with PDF_PASSWORDS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            password = (row.get("password") or "").strip()
            pdf_file = (row.get("pdf_file") or "").strip()

            if password:
                rows.append({
                    "pdf_file": pdf_file,
                    "password": password
                })

    return rows


@lru_cache(maxsize=1)
def get_password_list() -> list[str]:
    """Return unique passwords in order"""
    seen = set()
    ordered = []

    for row in load_password_rows():
        pwd = row["password"]
        if pwd not in seen:
            seen.add(pwd)
            ordered.append(pwd)

    return ordered


@lru_cache(maxsize=1)
def get_password_map() -> dict[str, str]:
    """Return filename → password mapping"""
    mapping = {}
    for row in load_password_rows():
        if row["pdf_file"]:
            mapping[row["pdf_file"]] = row["password"]
    return mapping


def build_password_candidates(path: Path, supplied_password: str = "") -> list[str]:
    """
    Build ordered list of passwords to try:
    1. supplied password
    2. filename-specific password
    3. full password list
    """
    candidates = []
    seen = set()

    def add(p):
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            candidates.append(p)

    add(supplied_password)
    add(get_password_map().get(path.name, ""))

    for pwd in get_password_list():
        add(pwd)

    return candidates


def decrypt_pdf(reader: PdfReader, path: Path, supplied_password: str = "") -> None:
    """Try all passwords until success"""
    if not reader.is_encrypted:
        return

    candidates = build_password_candidates(path, supplied_password)

    for pwd in candidates:
        try:
            result = reader.decrypt(pwd)
            if result:  # success
                print(f"Decrypted {path.name} using password")
                return
        except Exception:
            continue

    raise FileNotDecryptedError(f"{path.name} could not be decrypted with provided passwords")


def read_pdf_pages(path: Path, password: str = "") -> list[str]:
    """
    Always returns list[str]
    Raises FileNotDecryptedError if all passwords fail
    """
    reader = PdfReader(str(path))

    decrypt_pdf(reader, path, password)

    return [page.extract_text() or "" for page in reader.pages]