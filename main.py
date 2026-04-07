import csv

from fund_extractor.config import OUTPUT_CSV
import fund_extractor.config as FEC
from fund_extractor.pipeline import build_rows

List_Document_Passwords = []


def main() -> None:
    # Indices_Folder_List=["Gemlife","GIPF","NHE"]
    Indices_Folder_List = ["Gemlife", "NHE"]
    for i_f in Indices_Folder_List:
        FEC.SetDataDir(i_f)
        pdf_paths = sorted(FEC.DATA_DIR.glob("*.[Pp][Dd][Ff]"))
        all_rows: list[dict[str, str]] = []
        for pdf_path in pdf_paths:
            all_rows.extend(build_rows(pdf_path))
        FEC.SetOutputFName(i_f)
        with FEC.OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "pdf_file",
                    "provider",
                    "report_date",
                    "fund_value",
                    "fund_value_source",
                    "fund_value_page",
                    "column_headings",
                    "cashflow_date",
                    "cashflow_amount",
                    "cashflow_type",
                    "cashflow_source",
                    "status",
                ],
            )
            writer.writeheader()
            writer.writerows(all_rows)

        print(f"Wrote {len(all_rows)} rows to {FEC.OUTPUT_CSV}")


if __name__ == "__main__":
    main()
