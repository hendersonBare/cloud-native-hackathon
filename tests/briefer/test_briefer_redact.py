"""Redaction unit tests: emails, phone numbers and postal addresses, and text that must survive."""

from __future__ import annotations

import pytest

from rapport_memory.profiles import chunk_text
from rapport_memory.redact import PLACEHOLDER, redact


@pytest.mark.parametrize(
    "secret",
    [
        "ava.synthetic@example.com",
        "first+tag@sub.example.co.uk",
        "+1 (555) 010-1234",
        "555-010-1234",
        "(555) 010-1234",
        "555.010.1234",
        "+34 600 123 456",
        "5550101234",
        "12 Main Street",
        "1600 N. Example Avenue, Suite 4",
        "Denver, CO 80202",
        "PO Box 1234",
        "SW1A 1AA",
    ],
)
def test_contact_details_are_redacted(secret):
    out = redact(f"Reach me: {secret} any time.")
    assert secret not in out and PLACEHOLDER in out


def test_everything_in_a_cv_is_redacted_but_the_content_stays():
    cv = (
        "Ava Example\nEmail: ava@example.com | Phone: +1 555 010 1234\n12 Oak Lane, Denver, CO 80202\n"
        "Built eBPF tracing for Kubernetes 1.30 from 2019-2023."
    )
    out = redact(cv)
    for leaked in ("ava@example.com", "555 010 1234", "Oak Lane", "80202"):
        assert leaked not in out
    assert "eBPF tracing for Kubernetes 1.30 from 2019-2023" in out


def test_years_versions_and_percentages_are_left_alone():
    text = "Cut incident time 40% between 2019-2023 on Kubernetes 1.30 with 300 services in 2 regions."
    assert redact(text) == text


def test_chunking_is_about_1500_characters_and_loses_nothing():
    paras = [f"Paragraph {i}. " + "word " * 120 for i in range(10)]
    chunks = chunk_text("\n\n".join(paras))
    assert len(chunks) > 1 and all(len(c) <= 1600 for c in chunks)
    assert "".join(chunks).count("Paragraph") == 10
    assert chunk_text("x" * 4000) and all(len(c) <= 1500 for c in chunk_text("x" * 4000))
    assert chunk_text("   ") == []
