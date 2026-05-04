import csv
import re
import shutil
from pathlib import Path
import os
import pdfplumber
from mistralai import Mistral
from pdf2image import convert_from_path
import base64
try:
    import pytesseract
    OCR_AVAILABLE = True
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
except ImportError:
    pytesseract = None
    OCR_AVAILABLE = False





key_name = "PDF_Scan_Key"
key_secret ="z1K2BIiUBEkDUWkQUTDx5WKtlCYV7JsW"

PASSWORD_LIST = [
    "0005",             #NMC Capricorn Asset Management and NMC M&G
    "25/7/7/516",
    "25/7/7/6",         #UNIPOL IJG and UNIPOL Capricorn Asset Management
    "25/7/7/89",
    "25/7/7/18",
    "25/7/7/227",       #Namib Mills Capricorn Asset Management
    "25/7/7/36",
    "25/7/7/35",
    "25/7/7/50",        #Nampower Capricorn Asset Management
    "25/7/7/57",        #NHE IJG password
    "25/7/7/18",
    "25/7/7/110",
    "25/7/7/57",
    "ACC_1176_2387",    #Nampower OM
    "ACC_1726_3910",    #Unipol OM
    "NinetyOne"         #All NinetyOne Passwords
]

def clear_results_folder(results_path):
    if results_path.exists():
        shutil.rmtree(results_path)
    results_path.mkdir(exist_ok=True)
    print(f"🧹 Cleared results folder: {results_path}")

def extract_with_mistral(file_path, Fund_Prompt):

    client = Mistral(api_key=key_secret)

    # Step 1: Convert PDF to images
    images = convert_from_path(file_path)

    # Step 2: OCR each page
    full_text = ""
    for i, img in enumerate(images):
        text = pytesseract.image_to_string(img)
        full_text += f"\n--- PAGE {i+1} ---\n{text}"

    # Step 3: Send to Mistral
    prompt = f"""
    Extract the following information:

    {Fund_Prompt}

    Document content:
    {full_text}

    Important:
    - Numbers may contain spaces (e.g. 2 509 260.00 → 2509260.00)

    Return STRICT JSON:
    [
        {{
            "value": float,
            "context": string,
            "page": int
        }}
    ]

    Only return JSON.
    """

    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return response.choices[0].message.content




def open_pdf_with_passwords(file_path):
    """
    Try opening a PDF using a list of passwords
    """
    try:
        pdf = pdfplumber.open(file_path)
        return pdf
    except:
        pass

    # Try passwords
    for pwd in PASSWORD_LIST:
        try:
            pdf = pdfplumber.open(file_path, password=pwd)
            print(f"   🔓 Opened with password: {pwd}")
            return pdf
        except:
            continue

    print(f"   ❌ Failed to open (no valid password): {file_path.name}")
    return None


def get_fund_code(filename: str) -> str:
    """
    Returns a code based on keywords in the filename.
    
    Examples:
    "(AGP Smooth) ORION NAM PROV HIGH GROWTH - 28 FEBRUARY 2026.pdf" -> "AGPHigh"
    "(AGP Stable) GEMLIFE RETIREMENT FUND - 28 FEBRUARY 2026.pdf" -> "AGP"
    """

    
    # Normalize to uppercase for consistent matching
    
    if filename=="(CAM) 4056832_3741013_Investment statement_NAMPOWER PROVIDENT FUND_13843876_UT.pdf":
        temp=0
    name = filename.upper()

    result = ""

    
    
    

    # Base rule
    if "AGP" in name:
        result = "AGP"

        # Additional condition
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
        if "WITHDRAWALS"  in name:
            result += " Contributions and Withdrawals"
        if "MEDICAL CARE" in name:
            result = "SIM"


    
    if "UNLISTED DEBT" in name:
        result = "Sanlam Unlisted Debt"

    if "STIMULUS" in name:
        result = "Stimulus"
    
    if ("NAM" in name) and (result==""):
        result = "Namibia Asset Management"
        if "WITHDRAWALS"  in name:
            result += " Contributions and Withdrawals"
    
    
    if result=="":
        temp=0

    return result






def main():
    #AllanGray_Prompt="Go to the first table with the heading Effective exposure (N$). Go to the Total row which is the last row in the table and extract the Effective exposure (N$) value. The last row in this table could flow over onto the next page. Please consider this."
    AllanGray_Prompt="Please give me the all-in market value of the investment portfolio, not the book value"
    #Indices_List = ["GemLife", "GIPF","Namwater","NamibMills","Nampower","UNIPOL","NBC","NHE","NMC","ORION","UNIPOL"]
    Indices_List = ["GemLife"]
    
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

            try:
                
                fund_name = get_fund_code(file.name)
                if "Allan Gray" in fund_name:
                    mistral_output = extract_with_mistral(str(file), AllanGray_Prompt)
                if "IJG" in fund_name:
                    mistral_output = extract_with_mistral(str(file), "Please extract the indicative fair value inside this pdf file.")
                else:                    
                    mistral_output = extract_with_mistral(str(file), "Please extract the closing market value inside this pdf file")

                print("🔎 Mistral Output:")
                print(mistral_output)

                # OPTIONAL: store raw output
                all_rows.append([
                    file.name,
                    "MISTRAL",
                    "",
                    "",
                    mistral_output
                ])

            except Exception as e:
                print(f"❌ Mistral extraction failed: {e}")
                continue
            



        output = results_path / f"{i}.csv"

        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Source File","Table Name","Row","Column","Value"])
            writer.writerows(all_rows)

        print(f"\n✅ Output written: {output}")

    


if __name__ == "__main__":
    main()