from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.config import settings


class InvoiceOCRService:
    def __init__(self) -> None:
        self._ocr_engine = None
        self._init_error: str | None = None

    def _get_engine(self):
        if self._ocr_engine is not None:
            return self._ocr_engine
        if self._init_error is not None:
            raise RuntimeError(self._init_error)

        try:
            from paddleocr import PaddleOCR  # type: ignore

            self._ocr_engine = PaddleOCR(use_angle_cls=True, lang=settings.ocr_lang, use_gpu=settings.ocr_use_gpu)
            return self._ocr_engine
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            self._init_error = f"PaddleOCR init failed: {exc}"
            raise RuntimeError(self._init_error) from exc

    def run(self, file_path: str) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            return {"status": "failed", "error": "file not found", "fields": {}, "raw_text": ""}

        try:
            ocr = self._get_engine()
            result = ocr.ocr(str(path), cls=True)
            text = self._flatten_result_text(result)
            fields = self._extract_fields(text)
            status = "success"
            return {
                "status": status,
                "error": None,
                "fields": fields,
                "raw_text": text,
                "raw": {"text": text},
            }
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            return {"status": "failed", "error": str(exc), "fields": {}, "raw_text": "", "raw": {"error": str(exc)}}

    def _flatten_result_text(self, result: Any) -> str:
        if not result:
            return ""

        lines: list[str] = []
        for page in result:
            if not page:
                continue
            for line in page:
                if isinstance(line, list) and len(line) >= 2 and isinstance(line[1], (list, tuple)):
                    content = line[1][0]
                    if content:
                        lines.append(str(content).strip())
        return "\n".join(lines)

    def _extract_fields(self, text: str) -> dict[str, Any]:
        normalized = text.replace("：", ":")

        company_name = self._find_first(
            normalized,
            [
                r"(?:购买方|购方|销方|销售方)?名称\s*:?\s*([^\n]{2,80})",
                r"公司名称\s*:?\s*([^\n]{2,80})",
            ],
        )
        if company_name:
            company_name = company_name.strip(" _-:")

        tax_id = self._find_first(
            normalized,
            [
                r"纳税人识别号\s*:?\s*([0-9A-Z]{15,20})",
                r"税号\s*:?\s*([0-9A-Z]{15,20})",
                r"\b([0-9A-Z]{18})\b",
            ],
        )

        invoice_number = self._find_first(
            normalized,
            [
                r"发票号码\s*:?\s*([0-9]{6,20})",
                r"票据号码\s*:?\s*([0-9]{6,20})",
            ],
        )

        issue_date = self._extract_issue_date(normalized)
        item_name = self._extract_item_name(normalized)
        total_amount = self._extract_amount(normalized)

        return {
            "company_name": company_name,
            "tax_id": tax_id,
            "invoice_number": invoice_number,
            "issue_date": issue_date,
            "item_name": item_name,
            "total_amount": total_amount,
        }

    def _find_first(self, text: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_issue_date(self, text: str) -> str | None:
        patterns = [
            r"开票日期\s*:?\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)",
            r"日期\s*:?\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)",
        ]
        date_text = self._find_first(text, patterns)
        if not date_text:
            return None

        cleaned = date_text.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
        try:
            dt = datetime.strptime(cleaned, "%Y-%m-%d")
            return dt.date().isoformat()
        except ValueError:
            return None

    def _extract_item_name(self, text: str) -> str | None:
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate.startswith("*") and len(candidate) > 2:
                return candidate[:255]
            if any(key in candidate for key in ["服务费", "咨询费", "技术服务", "材料", "办公用品"]):
                return candidate[:255]
        return None

    def _extract_amount(self, text: str) -> str | None:
        candidates: list[str] = []

        for pattern in [
            r"价税合计\s*\(.*?\)\s*:?\s*([¥￥]?\s*[0-9,]+(?:\.[0-9]{1,2})?)",
            r"合计\s*:?\s*([¥￥]?\s*[0-9,]+(?:\.[0-9]{1,2})?)",
            r"总金额\s*:?\s*([¥￥]?\s*[0-9,]+(?:\.[0-9]{1,2})?)",
        ]:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                candidates.append(match.group(1))

        if not candidates:
            return None

        # Prefer the largest parsed value, which usually matches tax-included total.
        parsed_values: list[Decimal] = []
        for item in candidates:
            cleaned = item.replace("¥", "").replace("￥", "").replace(",", "").strip()
            try:
                parsed_values.append(Decimal(cleaned))
            except InvalidOperation:
                continue

        if not parsed_values:
            return None

        return str(max(parsed_values).quantize(Decimal("0.01")))


ocr_service = InvoiceOCRService()
