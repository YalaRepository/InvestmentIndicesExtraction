from pypdf import PdfReader, PdfWriter

reader = PdfReader(r"C:\Work\InvestmentIndicesExtraction\PDF_Data\Unipol\(OM) UNIGR1_FEB 2026.pdf")
reader.decrypt("ACC_1726_3910")

writer = PdfWriter()
for page in reader.pages:
    writer.add_page(page)

with open("unlocked.pdf", "wb") as f:
    writer.write(f)