from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.models import Invoice

_INVALID_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|\s]+')
_MULTIPLE_UNDERSCORES_RE = re.compile(r"_+")


def _sanitize_filename_part(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    text = _INVALID_FILENAME_CHARS_RE.sub("_", text)
    text = _MULTIPLE_UNDERSCORES_RE.sub("_", text).strip("._")
    return text[:100] if text else fallback


def _amount_to_filename_part(value: object) -> str:
    if value is None:
        return "unknown_amount"

    try:
        decimal_value = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return "unknown_amount"

    amount_text = f"{decimal_value:.2f}".replace(".", "_")
    # Keep minus sign if it exists.
    return _sanitize_filename_part(amount_text, "unknown_amount")


def build_invoice_download_name(invoice: Invoice) -> str:
    company_part = _sanitize_filename_part(invoice.company_name, "unknown_company")
    amount_part = _amount_to_filename_part(invoice.total_amount)
    base_name = f"{company_part}_{amount_part}"

    ext = (invoice.file_ext or "").strip()
    if not ext:
        ext = Path(invoice.file_path or "").suffix
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    return f"{base_name}{ext or ''}"
