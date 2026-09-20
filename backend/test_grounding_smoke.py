from pathlib import Path

from app.pdf_parse import ground_quote, parse_pdf

PDF = Path(__file__).resolve().parents[1] / "Veritas_Cloud_Master_Services_Agreement.pdf"
pages = parse_pdf(PDF.read_bytes())
checks = [
    (1, "All undisputed invoices are payable within seventy-five (75) days of the invoice date. Payment shall be made by wire transfer in United States Dollars without set-off or deduction.", "3.2", "Payment Terms"),
    (2, "The Supplier may increase the subscription fees effective on each renewal term by providing not less than thirty (30) days written notice prior to the commencement of that renewal term, provided that any such increase shall not exceed nine percent (9%) of the fees payable during the immediately preceding term.", "3.4", "Annual Price Adjustment"),
    (3, "The Customer may terminate this Agreement for convenience at any time during a term by providing sixty (60) days prior written notice, provided that the Customer pays an early termination fee of USD 45,000 together with all fees accrued up to the effective date of termination.", "9.1", "Termination for Convenience"),
]
for page, quote, num, title in checks:
    ev = ground_quote(pages, quote, page)
    assert ev["tier"] == 1, ev
    assert ev["section_number"] == num, ev
    assert ev["section"] == f"Section {num} {title}", ev
    assert ev["page"] == page, ev
print("grounding smoke: 3/3 passed")
