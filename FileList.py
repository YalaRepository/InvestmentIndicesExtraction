import os
import csv
from pathlib import Path

def list_files_to_csv(root_path, output_file="Files.csv", include_full_path=True):
    """
    Scans all subfolders in root_path and writes file names to a CSV.
    
    Parameters:
        root_path (str): Folder to scan
        output_file (str): Output CSV file name
        include_full_path (bool): If True, includes full file path
    """

    root = Path(root_path)

    if not root.exists():
        print(f"❌ Path does not exist: {root_path}")
        return

    file_list = []

    print(f"🔍 Scanning: {root_path}")

    for file in root.rglob("*"):
        if file.is_file():
            if include_full_path:
                file_list.append([file.name, str(file)])
            else:
                file_list.append([file.name])

    # Write to CSV
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        
        # Header
        if include_full_path:
            writer.writerow(["FileName", "FullPath"])
        else:
            writer.writerow(["FileName"])
        
        # Data
        writer.writerows(file_list)

    print(f"✅ Done! {len(file_list)} files written to {output_file}")


# =========================
# 🔧 USAGE
# =========================
if __name__ == "__main__":
    folder_to_scan = r"C:\Work\InvestmentIndicesExtraction\PDF_Data"  # 👈 CHANGE THIS
    list_files_to_csv(folder_to_scan)