import pdfplumber
import csv
import re
import shutil
from pathlib import Path

# OCR fallback
try:
    import pytesseract
    OCR_AVAILABLE = True
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
except ImportError:
    pytesseract = None
    OCR_AVAILABLE = False


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
    "25/7/7/18",
    "25/7/7/110",
    "25/7/7/57",
    "ACC_1176_2387",
    "ACC_1726_3910",
    "NinetyOne"
]


# ----------------------------
# CLEAN / HELPERS
# ----------------------------
def extract_agp_statement(page, file_name, page_num):
    text = page.extract_text()
    if not text:
        return []

    if "AGP" not in text and "Absolute Growth" not in text:
        return []

    if not re.search(r"Inflows|Outflows|Transaction Listing|Investment Return|Closing Balance", text, re.I):
        return []

    print("   🟦 Extracting AGP Stable statement...")

    rows = []
    table_name = f"AGPStatement_{page_num}"
    row_idx = 1

    lines = [clean_value(l) for l in text.split("\n") if clean_value(l)]

    for line in lines:

        # Summary rows on pages 1/2
        summary_match = re.match(
            r"^(Opening Balance|Inflows|Outflows|Investment Return|Closing Balance)\s+(.*)$",
            line,
            re.I
        )

        # Transaction rows on page 3
        txn_match = re.match(
            r"^(\d{2}/\d{2}/\d{4})\s+(Withdrawal|Contribution|Investment fees|Inflow|Outflow)\s+(.*)$",
            line,
            re.I
        )

        total_match = re.match(
            r"^(Inflow Total|Outflow Total)\s+(.*)$",
            line,
            re.I
        )

        if not (summary_match or txn_match or total_match):
            continue

        if txn_match:
            date = txn_match.group(1)
            label = txn_match.group(2)
            rest = txn_match.group(3)
            nums = extract_numbers(rest)

            output = [date, label] + [clean_value(n).replace(",", "") for n in nums]

        elif summary_match:
            label = summary_match.group(1)
            rest = summary_match.group(2)
            nums = extract_numbers(rest)

            output = ["", label] + [clean_value(n).replace(",", "") for n in nums]

        else:
            label = total_match.group(1)
            rest = total_match.group(2)
            nums = extract_numbers(rest)

            output = ["", label] + [clean_value(n).replace(",", "") for n in nums]

        for col_idx, val in enumerate(output, 1):
            rows.append([file_name, table_name, row_idx, col_idx, clean_value(val)])

        row_idx += 1

    return rows



def clean_value(val):
    if val is None:
        return ""

    val = str(val)
    val = val.replace("\n", " ").replace("\r", " ")
    val = re.sub(r"\s+", " ", val).strip()

    if re.search(r"\d,\d", val):
        val = val.replace(",", "")

    if val.startswith(("=", "+", "-", "@")):
        val = "'" + val

    return val


def clear_results_folder(results_path):
    if results_path.exists():
        shutil.rmtree(results_path)
    results_path.mkdir(exist_ok=True)
    print(f"🧹 Cleared results folder: {results_path}")


def expand_multiline_row(row):
    split_cells = []

    for cell in row:
        parts = str(cell).split("\n") if cell else [""]
        parts = [p.strip() for p in parts if p.strip()]
        split_cells.append(parts if parts else [""])

    max_len = max(len(c) for c in split_cells)

    for c in split_cells:
        c.extend([""] * (max_len - len(c)))

    return [[split_cells[j][i] for j in range(len(split_cells))] for i in range(max_len)]


def row_has_real_content(row):
    return any(clean_value(cell) for cell in row)


def normalise_date(date):
    date = re.sub(r"\s+", "", date)

    parts = date.split("/")
    if len(parts) == 3 and len(parts[2]) == 2:
        parts[2] = "20" + parts[2]

    return "/".join(parts)


def extract_numbers(text):
    return re.findall(r"\(?-?\d[\d,]*\.?\d*\)?%?", text)


# ----------------------------
# PDF OPENING
# ----------------------------

def open_pdf_with_passwords(file_path):
    try:
        pdf = pdfplumber.open(file_path)
        return pdf
    except:
        pass

    for pwd in PASSWORD_LIST:
        try:
            pdf = pdfplumber.open(file_path, password=pwd)
            print(f"   🔓 Opened with password: {pwd}")
            return pdf
        except:
            continue

    print(f"   ❌ Failed to open (no valid password): {file_path.name}")
    return None


# ----------------------------
# OCR
# ----------------------------

def get_page_text(page):
    if not OCR_AVAILABLE:
        print("   ❌ OCR not available")
        return ""

    try:
        print("   🔎 OCR running...")
        page_image = page.to_image(resolution=400).original.convert("RGB")

        text = pytesseract.image_to_string(
            page_image,
            lang="eng",
            config="--oem 3 --psm 6"
        )

        if text.strip():
            print("   ✅ OCR SUCCESS")
        else:
            print("   ⚠️ OCR returned empty text")

        return text.strip()

    except Exception as e:
        print(f"   ❌ OCR FAILED: {e}")
        return ""


# ----------------------------
# CONTRIBUTIONS / WITHDRAWALS - UPDATED ONLY
# ----------------------------

def extract_contributions_table(page, file_name, page_num):
    """
    Improved contributions/withdrawals extraction.

    Keeps your same output format:
    Source File, Table Name, Row, Column, Value

    But instead of relying on table spacing, it reconstructs logical rows.
    """

    text = page.extract_text()

    if not text:
        return []

    if not re.search(r"Contribution|Contributions|Withdrawal|Withdrawals", text, re.IGNORECASE):
        return []

    print("   💰 Reconstructing Contributions / Withdrawals Table...")

    lines = [clean_value(l) for l in text.split("\n") if clean_value(l)]

    rows = []
    table_name = f"Contributions_{page_num}"
    row_idx = 1

    current_row = []

    date_pattern = r"\d{2}\s*/\s*\d{2}\s*/\s*(?:\d{2}|\d{4})"

    skip_phrases = [
        "Settlement",
        "Trade",
        "Effective",
        "Entry",
        "Transaction",
        "Instrument",
        "Description",
        "Amount",
        "Contributions",
        "Contribution",
        "Withdrawals",
        "Withdrawal",
        "Total"
    ]

    for line in lines:

        if any(h.upper() in line.upper() for h in skip_phrases):
            continue

        if re.search(date_pattern, line):

            if current_row:
                rows.extend(
                    _process_contribution_row(
                        current_row,
                        file_name,
                        table_name,
                        row_idx
                    )
                )
                row_idx += 1

            current_row = [line]

        else:
            if current_row:
                current_row.append(line)

    if current_row:
        rows.extend(
            _process_contribution_row(
                current_row,
                file_name,
                table_name,
                row_idx
            )
        )

    return rows


def _process_contribution_row(row_lines, file_name, table_name, row_idx):
    full_line = clean_value(" ".join(row_lines))

    date_pattern = r"\d{2}\s*/\s*\d{2}\s*/\s*(?:\d{2}|\d{4})"
    date_match = re.search(date_pattern, full_line)

    date = ""
    if date_match:
        date = normalise_date(date_match.group(0))

    raw_nums = extract_numbers(full_line)

    desc = full_line

    for n in raw_nums:
        desc = desc.replace(n, "", 1)

    if date_match:
        desc = desc.replace(date_match.group(0), "")

    desc = clean_value(desc)

    numeric_values = []
    for n in raw_nums:
        temp = n.replace(",", "")
        temp = temp.replace("(", "-").replace(")", "")
        temp = temp.replace("%", "")

        try:
            numeric_values.append(float(temp))
        except:
            pass

    contribution = ""
    withdrawal = ""

    for v in numeric_values:
        if v < 0:
            withdrawal = abs(v)
        elif v > 0:
            contribution = v

    output = [
        date,
        desc,
        contribution,
        withdrawal
    ]

    rows = []

    for col_idx, val in enumerate(output, 1):
        rows.append([
            file_name,
            table_name,
            row_idx,
            col_idx,
            clean_value(val)
        ])

    return rows


# ----------------------------
# VALUATION ROWS
# ----------------------------

def extract_valuation_rows(page, file_name, page_num):
    text = page.extract_text()
    if not text:
        return []

    if "Valuation" not in text:
        return []

    lines = [clean_value(l) for l in text.split("\n") if clean_value(l)]
    rows = []
    table_name = f"Valuation_{page_num}"
    row_idx = 1

    skip_starts = (
        "Valuation",
        "As at ",
        "Namib Mills Retirement Fund",
        "The GEMLIFE Retirement Fund",
        "Security",
        "Code",
        "Security Name",
        "QTY",
        "Asset",
        "CCY",
        "Average",
        "Cost",
        "Market",
        "Price",
        "Book Value",
        "(NAD)",
        "Accrued",
        "Interest",
        "Unrealised",
        "Profit / (Loss)",
        "Market Value",
        "EMV",
        "% EMV",
    )

    for line in lines:
        if any(line.startswith(s) for s in skip_starts):
            continue

        if line in {"NO DATA FOR THE PERIOD"}:
            continue

        nums = re.findall(r"\(?-?\d[\d,]*\.?\d*\)?%?", line)
        if not nums:
            continue

        label = line
        for n in nums:
            label = label.replace(n, "", 1)
        label = clean_value(label)

        values = [clean_value(n).replace(",", "") for n in nums]

        output_cells = []
        if label:
            output_cells.append(label)
        output_cells.extend(values)

        if not output_cells:
            continue

        for col_idx, val in enumerate(output_cells, 1):
            rows.append([file_name, table_name, row_idx, col_idx, val])

        row_idx += 1

    return rows


# ----------------------------
# IJG STRUCTURED PARSER
# ----------------------------

def extract_ijg_structured(page, file_name, page_num):
    text = get_page_text(page)
    if not text:
        print("   ❌ No OCR text for IJG parsing")
        return []

    print("   🧠 Structured IJG parsing...")

    patterns = {
        "Commitment Amount": r"Commitment Amount.*?([\d,]+\.\d+)",
        "Undrawn Commitment": r"Undrawn Commitment.*?([\d,]+\.\d+)",
        "Drawdown": r"Commitment Amount Drawdown.*?([\d,]+\.\d+)",
        "Management Fee": r"Management Fee.*?([\d\.]+%)",
        "Commencement Date": r"Commencement Date.*?(\d{2} \w+ \d{4})",

        "Preference Share Investment": r"Preference Share Investment.*?([\d,]+\.\d+)",
        "Capital Drawn": r"Capital Drawn.*?([\d,]+\.\d+)",
        "Transaction Expenditure": r"Transaction Expenditure.*?([\d,]+\.\d+)",
        "Management Fees": r"Management Fees.*?([\d,]+\.\d+)",
        "Other Costs": r"Other.*?Costs.*?([\d,]+\.\d+)",

        "Fair Value": r"Indicative Fair Value.*?([\d,]+\.\d+)",
        "Investments": r"Investments.*?([\d,]+\.\d+)",
        "Cash": r"Cash and Cash Equivalents.*?([\d,]+\.\d+)",
        "Fair Value Adjustment": r"Fair Value Adjustments.*?\(?(-?[\d,]+\.\d+)\)?",

        "Opening Cash": r"Opening Balance.*?([\d,]+\.\d+)",
        "Movement": r"Movement.*?([\d,]+\.\d+)",
        "Closing Cash": r"Closing Balance.*?([\d,]+\.\d+)",
    }

    rows = []
    table_name = f"IJG_Structured_{page_num}"
    row_idx = 1

    for label, pattern in patterns.items():
        match = re.search(pattern, text, re.DOTALL)

        if match:
            value = match.group(1).replace(",", "")
            rows.append([file_name, table_name, row_idx, 1, label])
            rows.append([file_name, table_name, row_idx, 2, value])
            row_idx += 1
        else:
            print(f"   ⚠️ Missing: {label}")

    print(f"   ✅ Extracted {row_idx-1} IJG fields")

    return rows


# ----------------------------
# OM / PORTFOLIO FUNCTIONS
# ----------------------------

def extract_portfolio_summary_precise(page, file_name, page_num):
    text = page.extract_text()
    if not text or "PORTFOLIO SUMMARY OF ASSETS" not in text:
        return []

    print("   🎯 Extracting PORTFOLIO SUMMARY (precise mode)")

    rows = []
    table_name = f"PortfolioSummary_{page_num}"

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    row_idx = 1

    for line in lines:
        if any(h in line for h in [
            "PORTFOLIO SUMMARY",
            "Assets Book value",
            "Weight %",
            "Market value"
        ]):
            continue

        nums = re.findall(r"-?\d[\d,]*\.?\d*", line)

        if len(nums) < 2:
            continue

        label = line
        for n in nums:
            label = label.replace(n, "", 1)

        label = clean_value(label)
        nums = [clean_value(n).replace(",", "") for n in nums]

        output = [label] + nums if label else nums

        for col_idx, val in enumerate(output, 1):
            rows.append([file_name, table_name, row_idx, col_idx, val])

        row_idx += 1

    return rows


# ----------------------------
# BANK STATEMENT ROW RECONSTRUCTION
# ----------------------------

def extract_bank_statement_reconstructed(page, file_name, page_num):
    text = page.extract_text()

    if not text or "BANK STATEMENT" not in text:
        return []

    print("   🏦 Reconstructing BANK STATEMENT rows...")

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    rows = []
    table_name = f"BankStatement_{page_num}"

    current_row = []
    row_idx = 1

    date_pattern = r"\d{2}\s*/\s*\d{2}\s*/\s*(?:\d{2}|\d{4})"

    for line in lines:

        if any(h in line for h in [
            "BANK STATEMENT",
            "Transaction type",
            "Debit",
            "Credit",
            "Balance",
            "Universities Retirement Fund"
        ]):
            continue

        if re.search(date_pattern, line):

            if current_row:
                rows.extend(_process_bank_row(current_row, file_name, table_name, row_idx))
                row_idx += 1

            current_row = [line]

        else:
            if current_row:
                current_row.append(line)

    if current_row:
        rows.extend(_process_bank_row(current_row, file_name, table_name, row_idx))

    return rows


def _process_bank_row(row_lines, file_name, table_name, row_idx):

    full_line = " ".join(row_lines)

    date_pattern = r"\d{2}\s*/\s*\d{2}\s*/\s*(?:\d{2}|\d{4})"
    date_match = re.search(date_pattern, full_line)
    date = date_match.group(0) if date_match else ""

    date = re.sub(r"\s+", "", date)

    if date:
        parts = date.split("/")
        if len(parts) == 3 and len(parts[2]) == 2:
            parts[2] = "20" + parts[2]
        date = "/".join(parts)

    raw_nums = re.findall(r"-?\d[\d,]*\.?\d*", full_line)

    nums = []
    for n in raw_nums:
        cleaned = n.replace(" ", "")
        if re.match(r"^\d+(\.\d+)?$", cleaned):
            nums.append(cleaned)

    desc = full_line

    for n in raw_nums:
        desc = desc.replace(n, "", 1)

    desc = desc.replace(date, "")
    desc = clean_value(desc)

    output = [date, desc] + nums

    rows = []

    for col_idx, val in enumerate(output, 1):
        rows.append([file_name, table_name, row_idx, col_idx, val])

    return rows


def extract_bank_statement_precise(page, file_name, page_num):
    text = page.extract_text()
    if not text or "BANK STATEMENT" not in text:
        return []

    print("   🎯 Extracting BANK STATEMENT (precise mode)")

    rows = []
    table_name = f"BankStatement_{page_num}"

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    row_idx = 1

    for line in lines:

        if any(h in line for h in [
            "BANK STATEMENT",
            "Transaction type",
            "Debit",
            "Credit",
            "Balance",
            "Universities Retirement Fund"
        ]):
            continue

        if re.match(r"\d{2}/\d{2}/\d{2}", line):

            parts = re.split(r"\s{2,}", line)

            if len(parts) < 3:
                nums = re.findall(r"-?\d[\d,]*\.?\d*", line)
                label = line

                for n in nums:
                    label = label.replace(n, "", 1)

                parts = [clean_value(label)] + [clean_value(n) for n in nums]

            for col_idx, val in enumerate(parts, 1):
                rows.append([file_name, table_name, row_idx, col_idx, clean_value(val)])

            row_idx += 1

    return rows


# ----------------------------
# FALLBACK OCR DUMP
# ----------------------------

def extract_simple_financial_table(page, file_name, page_num):
    text = get_page_text(page)
    if not text:
        return []

    print("   🧠 Fallback OCR dump...")

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    rows = []
    table_name = f"SimpleTable_{page_num}"
    row_idx = 1

    for line in lines:
        cleaned = clean_value(line)
        if cleaned:
            rows.append([file_name, table_name, row_idx, 1, cleaned])
            row_idx += 1

    return rows


# ----------------------------
# NUMERIC SPLIT
# ----------------------------

def extract_valuation_lines_safe(page, file_name, page_num):
    text = page.extract_text()
    if not text:
        return []

    if "Valuation" not in text:
        return []

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    rows = []

    table_name = f"ValuationLines_{page_num}"
    row_idx = 1

    for line in lines:
        if re.search(r"\d", line) and len(line) > 20:

            rows.append([
                file_name,
                table_name,
                row_idx,
                1,
                clean_value(line)
            ])

            row_idx += 1

    return rows


def extract_total_portfolio_value(page, file_name, page_num):
    text = page.extract_text()
    if not text:
        return []

    rows = []
    table_name = f"Summary_{page_num}"

    pattern = r"(TOTAL PORTFOLIO VALUE|Total portfolio).*?([\d,]+\.\d+).*?([\d,]+\.\d+).*?(\d+\.\d+)"
    match = re.search(pattern, text, re.DOTALL)

    if match:
        label = match.group(1)
        book_val = match.group(2).replace(",", "")
        market_val = match.group(3).replace(",", "")
        perc = match.group(4)

        row_idx = 1

        rows.append([file_name, table_name, row_idx, 1, label])
        rows.append([file_name, table_name, row_idx, 2, book_val])
        rows.append([file_name, table_name, row_idx, 3, market_val])
        rows.append([file_name, table_name, row_idx, 4, perc])

        print("   ✅ TOTAL PORTFOLIO VALUE captured")

    return rows


def extract_lines_as_table(page, file_name, page_num):
    text = page.extract_text()
    if not text:
        return []

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    rows = []
    table_name = f"TextFallback_{page_num}"
    row_idx = 1

    for line in lines:
        if re.search(r"\d", line) and len(line) > 20:
            rows.append([
                file_name,
                table_name,
                row_idx,
                1,
                clean_value(line)
            ])
            row_idx += 1

    if rows:
        print("   ⚠️ No tables detected - using text fallback")

    return rows


def split_merged_numeric_cell(cell_value):
    if cell_value is None:
        return [""]

    text = clean_value(cell_value)
    nums = re.findall(r"-?\d[\d,]*\.?\d*", text)

    if len(nums) >= 2:
        label = text
        for n in nums:
            label = label.replace(n, "", 1)

        label = re.sub(r"\s+", " ", label).strip()

        if label:
            return [label] + nums

    return [text]


# ----------------------------
# COMBINE CSVs
# ----------------------------

def combine_result_csvs(results_path):
    combined_rows = []

    for csv_file in results_path.glob("*.csv"):
        if csv_file.name == "Combined.csv":
            continue

        print(f"🔗 Combining: {csv_file.name}")
        index = csv_file.stem

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=";")
            next(reader, None)

            for row in reader:
                combined_rows.append([index, *row])

    output = results_path / "Combined.csv"

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Index", "Source File", "Table Name", "Row", "Column", "Value"])
        writer.writerows(combined_rows)

    print(f"\n✅ Combined file written: {output}")


# ----------------------------
# FUND CODE
# ----------------------------

def get_fund_code(filename: str) -> str:

    name = filename.upper()
    result = ""

    if "AGP" in name:
        result = "AGP"
        if "HIGH" in name:
            result += " High"

    if "ALLAN GRAY" in name:
        result = "Allan Gray"

    if "ALLEGROW" in name:
        result = "Allegrow"

    if "CAM" in name:
        result = "Capricorn Asset Managers"

    if "CORE GROWTH" in name:
        result = "Core Growth"

    if "IJG" in name:
        result = "IJG"

    if "M&G" in name:
        result = "M&G"

    if "NINETY ONE" in name:
        result = "Ninety One"

    if "(OM" in name:
        result = "Old Mutual"

    if "SANLAM" in name:
        result = "Sanlam"
        if "WITHDRAWALS" in name:
            result += " Contributions and Withdrawals"
        if "MEDICAL CARE" in name:
            result = "SIM"

    if "UNLISTED DEBT" in name:
        result = "Sanlam Unlisted Debt"

    if "STIMULUS" in name:
        result = "Stimulus"

    if ("NAM" in name) and (result == ""):
        result = "Namibia Asset Management"
        if "WITHDRAWALS" in name:
            result += " Contributions and Withdrawals"

    return result


# ----------------------------
# MAIN
# ----------------------------

def main():

    Indices_List = [
        "GemLife",
        "GIPF",
        "Namwater",
        "NamibMills",
        "Nampower",
        "UNIPOL",
        "NBC",
        "NHE",
        "NMC",
        "ORION",
        "UNIPOL"
    ]

    base_path = Path(r"C:\Work\InvestmentIndicesExtraction\PDF_Data")
    results_path = Path(r"C:\Work\InvestmentIndicesExtraction\Results")

    clear_results_folder(results_path)

    for i in Indices_List:
        folder = base_path / i
        files = list(folder.glob("*.pdf")) if folder.exists() else []

        print(f"\n📂 Processing folder: {folder}")

        all_rows = []

        for file in files:
            print(f"\n📄 Processing file: {file.name}")

            try:
                pdf = open_pdf_with_passwords(file_path=file)
            except:
                print(f"❌ Failed to open: {file.name}")
                continue

            if pdf is None:
                continue

            is_ijg = "IJG" in file.name.upper()

            with pdf:
                for p_num, page in enumerate(pdf.pages, 1):
                    agp_rows = extract_agp_statement(page, get_fund_code(file.name), p_num)
                    if agp_rows:
                        all_rows.extend(agp_rows)
                        continue
                    
                    contrib_rows = extract_contributions_table(page, get_fund_code(file.name), p_num)
                    if contrib_rows:
                        all_rows.extend(contrib_rows)
                        continue

                    contrib_rows = extract_contributions_table(
                        page,
                        get_fund_code(file.name),
                        p_num
                    )
                    if contrib_rows:
                        all_rows.extend(contrib_rows)
                        continue

                    bank_rows = extract_bank_statement_reconstructed(
                        page,
                        get_fund_code(file.name),
                        p_num
                    )
                    if bank_rows:
                        all_rows.extend(bank_rows)
                        continue

                    portfolio_rows = extract_portfolio_summary_precise(
                        page,
                        get_fund_code(file.name),
                        p_num
                    )
                    if portfolio_rows:
                        all_rows.extend(portfolio_rows)
                        continue

                    valuation_rows = extract_valuation_rows(
                        page,
                        get_fund_code(file.name),
                        p_num
                    )
                    all_rows.extend(valuation_rows)

                    total_rows = extract_total_portfolio_value(
                        page,
                        get_fund_code(file.name),
                        p_num
                    )
                    all_rows.extend(total_rows)

                    if is_ijg:
                        print(f"   🔥 IJG structured extraction page {p_num}")
                        rows = extract_ijg_structured(
                            page,
                            get_fund_code(file.name),
                            p_num
                        )

                        if rows:
                            all_rows.extend(rows)
                        else:
                            print("   ⚠️ Structured failed → fallback OCR")
                            all_rows.extend(
                                extract_simple_financial_table(
                                    page,
                                    get_fund_code(file.name),
                                    p_num
                                )
                            )
                        continue

                    tables = page.extract_tables()

                    if tables:
                        for t_idx, table in enumerate(tables, 1):
                            if not table:
                                continue

                            real_rows = [r for r in table if row_has_real_content(r)]
                            if not real_rows:
                                continue

                            print(f"   📊 Extracting Table_{p_num}_{t_idx}")

                            table_name = f"Table_{p_num}_{t_idx}"
                            row_counter = 1

                            for row in real_rows:
                                for er in expand_multiline_row(row):

                                    new_row = []
                                    for cell in er:
                                        new_row.extend(split_merged_numeric_cell(cell))

                                    if not any(clean_value(v) for v in new_row):
                                        continue

                                    for col_idx, val in enumerate(new_row, 1):
                                        all_rows.append([
                                            get_fund_code(file.name),
                                            table_name,
                                            row_counter,
                                            col_idx,
                                            clean_value(val)
                                        ])

                                    row_counter += 1
                    else:
                        fallback_rows = extract_lines_as_table(
                            page,
                            get_fund_code(file.name),
                            p_num
                        )
                        all_rows.extend(fallback_rows)

        output = results_path / f"{i}.csv"

        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Source File", "Table Name", "Row", "Column", "Value"])
            writer.writerows(all_rows)

        print(f"\n✅ Output written: {output}")

    combine_result_csvs(results_path)


if __name__ == "__main__":
    main()