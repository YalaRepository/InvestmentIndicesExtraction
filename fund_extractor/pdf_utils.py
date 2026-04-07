from __future__ import annotations

import tempfile
from pathlib import Path

import pikepdf
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError


# 🔐 Global password list
PASSWORD_LIST = [
    "0005",
    "25/7/7/516",
    "25/7/7/6",
    "25/7/7/89",
    "25/7/7/18",
    "25/7/7/227",
    "25/7/7/36",
    "25/7/7/35",
    "25/7/7/50",
    "25/7/7/57",
    "25/7/7/89",
    "25/7/7/18",
    "25/7/7/110",
    "25/7/7/57",
    "NinetyOne"
]


def get_password_candidates(supplied_password: str = "") -> list[str]:
    """
    Build ordered password list:
    1. supplied password
    2. global PASSWORD_LIST (deduplicated)
    """
    seen = set()
    candidates = []

    def add(p):
        if p and p not in seen:
            seen.add(p)
            candidates.append(p)

    add(supplied_password)

    for pwd in PASSWORD_LIST:
        add(pwd)

    return candidates


def _read_unencrypted(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise FileNotDecryptedError(f"{path.name} still encrypted after decryption step")
    return [page.extract_text() or "" for page in reader.pages]


def _try_pypdf(path: Path, candidates: list[str]) -> list[str]:
    reader = PdfReader(str(path))

    if not reader.is_encrypted:
        print(f"{path.name}: not encrypted")
        return [page.extract_text() or "" for page in reader.pages]

    for pwd in candidates:
        try:
            result = reader.decrypt(pwd)
            print(f"{path.name}: pypdf tried {repr(pwd)} -> {result}")

            if result in (1, 2):  # success
                return [page.extract_text() or "" for page in reader.pages]

        except Exception as e:
            print(f"{path.name}: pypdf error with {repr(pwd)} -> {e}")

    raise FileNotDecryptedError(f"{path.name}: pypdf failed all passwords")


def _try_pikepdf(path: Path, candidates: list[str]) -> list[str]:
    temp_path = None

    try:
        for pwd in candidates:
            try:
                with pikepdf.open(str(path), password=pwd) as pdf:
                    print(
                        f"{path.name}: pikepdf SUCCESS with {repr(pwd)} "
                        f"(user={pdf.user_password_matched}, owner={pdf.owner_password_matched})"
                    )

                    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                    temp_path = tmp.name
                    tmp.close()

                    # Save decrypted version
                    pdf.save(temp_path)

                return _read_unencrypted(Path(temp_path))

            except Exception as e:
                print(f"{path.name}: pikepdf failed {repr(pwd)} -> {e}")

        raise FileNotDecryptedError(f"{path.name}: pikepdf failed all passwords")

    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


def read_pdf_pages(path: Path, password: str = "") -> list[str]:
    """
    Main entry point:
    1. Try pypdf
    2. Fallback to pikepdf
    """
    candidates = get_password_candidates(password)

    print(f"{path.name}: trying {len(candidates)} passwords")

    # Try pypdf first
    try:
        return _try_pypdf(path, candidates)
    except Exception as e:
        print(f"{path.name}: pypdf failed -> {e}")

    # Fallback to pikepdf
    try:
        return _try_pikepdf(path, candidates)
    except Exception as e:
        print(f"{path.name}: pikepdf failed -> {e}")
        raise FileNotDecryptedError(f"{path.name}: could not be decrypted with any password")