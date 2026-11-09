"""Contact-detail redaction (SPEC 4.3 step 2).

Emails, phone numbers and postal addresses become "[redacted]". The briefer calls `redact()` on uploaded
text BEFORE any LLM call and before anything is indexed. Patterns favour removing too much over too little.
"""

from __future__ import annotations

import re

PLACEHOLDER = "[redacted]"

_STREET_WORDS = (
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|way|place|pl|square|sq|"
    r"parkway|pkwy|terrace|highway|hwy|calle|avenida|carrera)"
)

_PATTERNS: list[re.Pattern[str]] = [
    # emails
    re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+"),
    # international phone numbers: +34 600 123 456, +1 (555) 010-1234
    re.compile(r"\+\d[\d \t().-]{7,}\d"),
    # US style: (555) 010-1234, 555-010-1234, 555.010.1234
    re.compile(r"(?<![\w-])\(?\d{3}\)?[ \t.-]\d{3}[ \t.-]\d{4}(?![\w-])"),
    # local seven digit numbers: 010-1234
    re.compile(r"(?<![\w-])\d{3}[ \t.-]\d{4}(?![\w-])"),
    # long bare digit runs
    re.compile(r"(?<!\w)\d{10,15}(?!\w)"),
    # street addresses: 12 Main Street, Suite 4 / 1600 N. Example Ave Apt 3
    re.compile(
        r"\b\d{1,6}[ \t]+(?:[A-Za-z0-9.'-]+[ \t]+){0,4}" + _STREET_WORDS + r"\b\.?"
        r"(?:,?[ \t]+(?:suite|ste|apt|unit|floor|fl)\.?[ \t]*#?[ \t]*[\w-]+)?",
        re.IGNORECASE,
    ),
    # City, ST 80202 (US) with optional ZIP+4
    re.compile(r"\b(?:[A-Z][a-z]+[ \t]?){1,3},[ \t]*[A-Z]{2}[ \t]+\d{5}(?:-\d{4})?\b"),
    # bare US ZIP+4
    re.compile(r"(?<![\w-])\d{5}-\d{4}(?![\w-])"),
    # PO boxes
    re.compile(r"\bP\.?\s?O\.?\s+Box\s+\d+\b", re.IGNORECASE),
    # UK postcodes
    re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b"),
]


def redact(text: str) -> str:
    """Replace emails, phone numbers and postal addresses with "[redacted]"."""
    for pattern in _PATTERNS:
        text = pattern.sub(PLACEHOLDER, text)
    return text
