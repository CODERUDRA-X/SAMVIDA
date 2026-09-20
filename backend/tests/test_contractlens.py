from pathlib import Path

import pytest

from app import risk, timeline
from app.knowledge_graph import build_knowledge_graph
from app.local_extract import extract as local_extract
from app.pdf_parse import Document, ground_quote, parse_pdf
from app.verification import CONFLICTING_EVIDENCE, SUPPORTED, verify_finding

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "Veritas_Cloud_Master_Services_Agreement.pdf"


@pytest.fixture(scope="module")
def doc():
    pages = parse_pdf(PDF.read_bytes())
    return Document.from_pages(pages)


def test_document_hierarchy_and_payment_section(doc):
    assert doc.clause("3.2")
    assert doc.clause("3.2").title == "Payment Terms"
    assert "days of the invoice" in doc.clause_text("3.2")


def test_payment_quote_grounds_to_section_3_2(doc):
    q = "All undisputed invoices are payable within seventy-five (75) days of the invoice date."
    ev = ground_quote(doc.pages, q, 1)
    assert ev["tier"] == 1
    assert ev["page"] == 1
    assert ev["section_number"] == "3.2"
    assert len(ev["rects"]) >= 1


def test_verification_catches_number_conflict(doc):
    ev = ground_quote(doc.pages, "All undisputed invoices are payable within seventy-five (75) days of the invoice date.", 1)
    f = {"quote": ev["excerpt"], "summary": "Invoices are payable within 90 days.", "date": "", "party": "Customer"}
    out = verify_finding(f, doc, ev)
    assert out["verification_status"] == CONFLICTING_EVIDENCE


def test_risk_policy_is_explicit(doc):
    f = {"quote": "All undisputed invoices are payable within seventy-five (75) days of the invoice date.", "summary": "Payment term", "label": "Payment term", "category": "payment"}
    out = risk.assess(f)
    assert out["risk"] == risk.HIGH
    assert out["ruleId"] == "R2-PAYMENT-TERM"


def test_local_demo_timeline_separates_time_and_decision(doc, monkeypatch):
    monkeypatch.setenv("CONTRACTLENS_TODAY", "2026-09-20")
    data = local_extract(doc)
    findings = []
    for i, f in enumerate(data["findings"]):
        f = dict(f)
        f["id"] = f"f{i}"
        f["evidence"] = ground_quote(doc.pages, f["quote"], f["page"])
        f = risk.assess(f)
        findings.append(f)
    items, _ = timeline.build_timeline(findings, data["effectiveDate"], data["expirationDate"])
    renewal = next(x for x in items if x["title"] == "Automatic renewal")
    assert renewal["date"] == "2026-12-31"
    assert renewal["temporal_status"] == "UPCOMING"
    assert renewal["decision_status"] == "PENDING"
    payment = next(x for x in items if x["title"] == "Payment term")
    assert payment["temporal_status"] == "RELATIVE"
    assert payment["basis"] == "75 days after invoice date"
    fee = next(x for x in items if x["title"] == "Termination for convenience")
    assert fee["fee"] == "USD 45,000"


def test_knowledge_graph_and_cross_clause_edges(doc):
    kg = build_knowledge_graph(doc)
    relations = {e.rel for e in kg.edges}
    assert "REQUIRES_NOTICE" in relations
    assert "CONDITIONAL_ON" in relations
    assert "SURVIVES_TERMINATION" in relations
