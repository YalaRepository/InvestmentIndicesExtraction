import csv
from collections import defaultdict

from fund_extractor.config import (
    DATA_ROOT,
    OUTPUT_DIR,
    get_output_csv,
    get_output_xlsx,
    get_summary_csv,
    get_summary_xlsx,
)
from fund_extractor.excel_writer import write_xlsx
from fund_extractor.pipeline import build_rows
from fund_extractor.providers import build_document_context


FIELDNAMES = [
    "index_name",
    "pdf_file",
    "provider",
    "document_type",
    "report_date",
    "fund_value",
    "fund_value_status",
    "fund_value_source",
    "fund_value_page",
    "column_headings",
    "cashflow_status",
    "cashflow_date",
    "cashflow_amount",
    "cashflow_type",
    "cashflow_source",
    "status",
]

SUMMARY_FIELDNAMES = [
    "index_name",
    "provider",
    "document_type",
    "status",
    "row_count",
    "unique_pdf_count",
    "fund_value_found_count",
    "fund_value_not_found_count",
    "cashflow_found_count",
    "cashflow_not_found_count",
]

# Set to `None` to run all index folders under `Data`.
# Set to an index folder name in the data folder like `"Gemlife"` to run only that index.
#TARGET_INDEX: str | None = None
TARGET_INDEX = "Gemlife" 


def iter_index_folders() -> list[str]:
    available = sorted(path.name for path in DATA_ROOT.iterdir() if path.is_dir())
    if TARGET_INDEX is None:
        return available
    if TARGET_INDEX not in available:
        raise ValueError(
            f"TARGET_INDEX {TARGET_INDEX!r} was not found in {DATA_ROOT}. "
            f"Available options: {', '.join(available)}"
        )
    return [TARGET_INDEX]


def iter_pdf_contexts(index_name: str) -> list:
    index_dir = DATA_ROOT / index_name
    pdf_paths = sorted(index_dir.rglob("*.[Pp][Dd][Ff]"))
    return [build_document_context(pdf_path) for pdf_path in pdf_paths]


def build_summary_rows(all_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str], dict[str, object]] = defaultdict(
        lambda: {
            "pdf_files": set(),
            "row_count": 0,
            "fund_value_found_count": 0,
            "fund_value_not_found_count": 0,
            "cashflow_found_count": 0,
            "cashflow_not_found_count": 0,
        }
    )

    for row in all_rows:
        key = (
            row["index_name"],
            row["provider"],
            row["document_type"],
            row["status"],
        )
        bucket = grouped[key]
        bucket["row_count"] += 1
        bucket["pdf_files"].add(row["pdf_file"])
        if row["fund_value_status"] == "found":
            bucket["fund_value_found_count"] += 1
        else:
            bucket["fund_value_not_found_count"] += 1
        if row["cashflow_status"] == "found":
            bucket["cashflow_found_count"] += 1
        else:
            bucket["cashflow_not_found_count"] += 1

    summary_rows: list[dict[str, str]] = []
    for key in sorted(grouped):
        index_name, provider, document_type, status = key
        bucket = grouped[key]
        summary_rows.append(
            {
                "index_name": index_name,
                "provider": provider,
                "document_type": document_type,
                "status": status,
                "row_count": str(bucket["row_count"]),
                "unique_pdf_count": str(len(bucket["pdf_files"])),
                "fund_value_found_count": str(bucket["fund_value_found_count"]),
                "fund_value_not_found_count": str(bucket["fund_value_not_found_count"]),
                "cashflow_found_count": str(bucket["cashflow_found_count"]),
                "cashflow_not_found_count": str(bucket["cashflow_not_found_count"]),
            }
        )
    return summary_rows


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combined_rows: list[dict[str, str]] = []

    for index_name in iter_index_folders():
        contexts = iter_pdf_contexts(index_name)
        all_rows: list[dict[str, str]] = []

        for context in contexts:
            all_rows.extend(build_rows(context))

        output_csv = get_output_csv(index_name)
        output_xlsx = get_output_xlsx(index_name)
        with output_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(all_rows)

        write_xlsx(all_rows, FIELDNAMES, output_xlsx)
        combined_rows.extend(all_rows)
        print(f"Wrote {len(all_rows)} rows to {output_csv} and {output_xlsx}")

    summary_rows = build_summary_rows(combined_rows)
    summary_csv = get_summary_csv()
    summary_xlsx = get_summary_xlsx()
    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(summary_rows)

    write_xlsx(summary_rows, SUMMARY_FIELDNAMES, summary_xlsx)
    print(f"Wrote {len(summary_rows)} summary rows to {summary_csv} and {summary_xlsx}")


if __name__ == "__main__":
    main()
