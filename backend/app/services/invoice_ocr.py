from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class InvoiceOCRService:
    def __init__(self) -> None:
        self._ocr_engine_gpu = None
        self._ocr_engine_cpu = None
        self._init_error_gpu: str | None = None
        self._init_error_cpu: str | None = None

    def _get_engine(self, use_gpu: bool):
        engine = self._ocr_engine_gpu if use_gpu else self._ocr_engine_cpu
        init_error = self._init_error_gpu if use_gpu else self._init_error_cpu
        if engine is not None:
            return engine
        if init_error is not None:
            raise RuntimeError(init_error)

        try:
            from paddleocr import PaddleOCR  # type: ignore

            engine = PaddleOCR(use_angle_cls=True, lang=settings.ocr_lang, use_gpu=use_gpu)
            if use_gpu:
                self._ocr_engine_gpu = engine
            else:
                self._ocr_engine_cpu = engine
            logger.info("PaddleOCR initialized. use_gpu=%s lang=%s", use_gpu, settings.ocr_lang)
            return engine
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            err = f"PaddleOCR init failed: {exc}"
            if use_gpu:
                self._init_error_gpu = err
            else:
                self._init_error_cpu = err
            logger.exception("PaddleOCR init failed. use_gpu=%s lang=%s", use_gpu, settings.ocr_lang)
            raise RuntimeError(err) from exc

    def run(self, file_path: str) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            logger.warning("OCR skipped: file not found: %s", file_path)
            return {
                "status": "failed",
                "error": "file not found",
                "fields": {},
                "raw_text": "",
                "raw": {"error": "file not found"},
            }

        preferred_gpu = settings.ocr_use_gpu
        try:
            ocr = self._get_engine(use_gpu=preferred_gpu)
            result = ocr.ocr(str(path), cls=True)
            text = self._flatten_result_text(result)
            fields = self._extract_fields(text)
            status = "success"
            return {
                "status": status,
                "error": None,
                "fields": fields,
                "raw_text": text,
                "raw": {"text": text, "used_gpu": preferred_gpu},
            }
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            if preferred_gpu:
                logger.warning("GPU OCR failed, trying CPU fallback. file=%s error=%s", file_path, exc)
                try:
                    ocr_cpu = self._get_engine(use_gpu=False)
                    result = ocr_cpu.ocr(str(path), cls=True)
                    text = self._flatten_result_text(result)
                    fields = self._extract_fields(text)
                    return {
                        "status": "success",
                        "error": None,
                        "fields": fields,
                        "raw_text": text,
                        "raw": {
                            "text": text,
                            "used_gpu": False,
                            "fallback_from_gpu_error": str(exc),
                        },
                    }
                except Exception as cpu_exc:  # pragma: no cover - runtime environment dependent
                    logger.exception("OCR execution failed after CPU fallback. file=%s", file_path)
                    return {
                        "status": "failed",
                        "error": str(cpu_exc),
                        "fields": {},
                        "raw_text": "",
                        "raw": {
                            "error": str(cpu_exc),
                            "gpu_error": str(exc),
                            "engine_init_error_gpu": self._init_error_gpu,
                            "engine_init_error_cpu": self._init_error_cpu,
                            "use_gpu": settings.ocr_use_gpu,
                            "lang": settings.ocr_lang,
                        },
                    }

            logger.exception("OCR execution failed for file=%s", file_path)
            return {
                "status": "failed",
                "error": str(exc),
                "fields": {},
                "raw_text": "",
                "raw": {
                    "error": str(exc),
                    "engine_init_error_gpu": self._init_error_gpu,
                    "engine_init_error_cpu": self._init_error_cpu,
                    "use_gpu": settings.ocr_use_gpu,
                    "lang": settings.ocr_lang,
                },
            }

    def health(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "use_gpu": settings.ocr_use_gpu,
            "lang": settings.ocr_lang,
            "engine_initialized_gpu": self._ocr_engine_gpu is not None,
            "engine_initialized_cpu": self._ocr_engine_cpu is not None,
            "init_error_gpu": self._init_error_gpu,
            "init_error_cpu": self._init_error_cpu,
        }
        try:
            self._get_engine(use_gpu=settings.ocr_use_gpu)
            data["ok"] = True
            data["engine_initialized_gpu"] = self._ocr_engine_gpu is not None
            data["engine_initialized_cpu"] = self._ocr_engine_cpu is not None
            data["init_error_gpu"] = self._init_error_gpu
            data["init_error_cpu"] = self._init_error_cpu
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            data["ok"] = False
            data["error"] = str(exc)
            data["engine_initialized_gpu"] = self._ocr_engine_gpu is not None
            data["engine_initialized_cpu"] = self._ocr_engine_cpu is not None
            data["init_error_gpu"] = self._init_error_gpu
            data["init_error_cpu"] = self._init_error_cpu
        return data

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
        normalized = self._normalize_text(text)
        railway_fields = self._extract_railway_ticket_fields(normalized)

        company_name = railway_fields.get("company_name") or self._find_first(
            normalized,
            [
                r"(?:购买方|购方|销方|销售方)?名称\s*:?\s*([^\n]{2,80})",
                r"公司名称\s*:?\s*([^\n]{2,80})",
            ],
        )
        if company_name:
            company_name = company_name.strip(" _-:")

        tax_id = railway_fields.get("tax_id") or self._extract_tax_id(normalized)

        invoice_number = railway_fields.get("invoice_number") or self._find_first(
            normalized,
            [
                r"发票号码\s*:?\s*([0-9]{6,20})",
                r"票据号码\s*:?\s*([0-9]{6,20})",
            ],
        )

        issue_date = railway_fields.get("issue_date") or self._extract_issue_date(normalized)
        item_name = railway_fields.get("item_name") or self._extract_item_name(normalized)
        total_amount = railway_fields.get("total_amount") or self._extract_amount(normalized)

        fields = {
            "company_name": company_name,
            "tax_id": tax_id,
            "invoice_number": invoice_number,
            "issue_date": issue_date,
            "item_name": item_name,
            "total_amount": total_amount,
        }
        if railway_fields:
            fields.update(
                {
                    "document_type": "railway_ticket",
                    "ticket_number": railway_fields.get("ticket_number"),
                    "departure_station": railway_fields.get("departure_station"),
                    "arrival_station": railway_fields.get("arrival_station"),
                    "train_number": railway_fields.get("train_number"),
                    "travel_date": railway_fields.get("travel_date"),
                    "departure_time": railway_fields.get("departure_time"),
                    "seat_type": railway_fields.get("seat_type"),
                    "seat_number": railway_fields.get("seat_number"),
                    "passenger_name": railway_fields.get("passenger_name"),
                }
            )
        return fields

    def _find_first(self, text: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _normalize_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text or "")
        normalized = normalized.replace("：", ":").replace("（", "(").replace("）", ")")
        return normalized

    def _clean_tax_id_candidate(self, raw: str) -> str:
        return re.sub(r"[^0-9A-Z]", "", (raw or "").upper())

    def _normalize_tax_id_candidate(self, raw: str) -> str:
        cleaned = self._clean_tax_id_candidate(raw)
        # OCR often confuses O/I/L with 0/1 on taxpayer id strings.
        return cleaned.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))

    def _is_tax_id_like(self, value: str) -> bool:
        return 15 <= len(value) <= 20 and value.isalnum()

    def _extract_tax_id(self, text: str) -> str | None:
        keyword_text = r"(?:统一社会信用代码(?:\s*/\s*纳税人识别号)?|社会信用代码(?:\s*/\s*纳税人识别号)?|纳税人识别号|纳税识别号|税号)"
        keyword_regex = re.compile(keyword_text, flags=re.IGNORECASE)
        candidate_regex = re.compile(r"([0-9A-Z][0-9A-Z\-\s]{14,30}[0-9A-Z])", flags=re.IGNORECASE)
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        for idx, line in enumerate(lines):
            if not keyword_regex.search(line):
                continue
            window = " ".join(lines[idx : idx + 3])
            for match in candidate_regex.finditer(window):
                cleaned = self._normalize_tax_id_candidate(match.group(1))
                if self._is_tax_id_like(cleaned):
                    return cleaned

        for pattern in [
            rf"{keyword_text}\s*[:：]?\s*([0-9A-Z\-\s]{{15,30}})",
            r"\b([0-9A-Z]{18})\b",
            r"\b([0-9A-Z]{15})\b",
        ]:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                cleaned = self._normalize_tax_id_candidate(match.group(1))
                if self._is_tax_id_like(cleaned):
                    return cleaned

        return None

    def _extract_issue_date(self, text: str) -> str | None:
        patterns = [
            r"开票日期\s*:?\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)",
            r"日期\s*:?\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)",
        ]
        date_text = self._find_first(text, patterns)
        if not date_text:
            return None

        return self._parse_date_text(date_text)

    def _parse_date_text(self, raw: str) -> str | None:
        cleaned = (raw or "").replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
        try:
            dt = datetime.strptime(cleaned, "%Y-%m-%d")
            return dt.date().isoformat()
        except ValueError:
            return None

    def _is_railway_ticket(self, text: str) -> bool:
        keywords = ["铁路电子客票", "电子客票号", "买票请到12306", "中国铁路"]
        if any(keyword in text for keyword in keywords):
            return True

        station_matches = re.findall(r"([\u4e00-\u9fff]{2,20}站)", text)
        has_train_number = bool(re.search(r"(?<![A-Z0-9])([GDCZTKYSLP]\d{1,5})(?![A-Z0-9])", text, flags=re.IGNORECASE))
        return len(station_matches) >= 2 and has_train_number

    def _extract_railway_ticket_fields(self, text: str) -> dict[str, Any]:
        if not self._is_railway_ticket(text):
            return {}

        stations = self._extract_railway_stations(text)
        departure_station = stations[0] if len(stations) >= 1 else None
        arrival_station = stations[1] if len(stations) >= 2 else None
        train_number = self._find_first(
            text,
            [r"(?<![A-Z0-9])([GDCZTKYSLP]\d{1,5})(?![A-Z0-9])"],
        )
        seat_type = self._find_first(
            text,
            [r"(商务座|特等座|一等座|二等座|软卧|硬卧|软座|硬座|无座|高级软卧|动卧|二等卧|一等卧)"],
        )
        seat_number = self._find_first(
            text,
            [
                r"(\d{1,2}车\d{1,3}[A-Z]号?)",
                r"(\d{1,3}[A-Z]号)",
            ],
        )
        departure_time = self._find_first(text, [r"(\d{1,2}:\d{2})\s*开"])
        travel_date_text = self._find_first(
            text,
            [
                r"((?:19|20)\d{2}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)\s+\d{1,2}:\d{2}\s*开",
                r"乘车日期\s*:?\s*((?:19|20)\d{2}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)",
            ],
        )
        company_name = self._find_first(text, [r"购买方名称\s*:?\s*([^\n]{2,80})"])
        if company_name:
            company_name = company_name.strip(" _-:")

        tax_id = self._extract_tax_id(text)
        invoice_number = self._find_first(text, [r"发票号码\s*:?\s*([0-9]{6,20})"])
        ticket_number = self._find_first(text, [r"电子客票号\s*:?\s*([0-9A-Z]{10,40})"])
        price_text = self._find_first(text, [r"票价\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)"])
        total_amount = None
        if price_text:
            parsed_amount = self._parse_amount(price_text)
            if parsed_amount is not None:
                total_amount = str(parsed_amount.quantize(Decimal("0.01")))

        passenger_name = self._extract_railway_passenger_name(text)

        item_parts = []
        route_text = None
        if departure_station and arrival_station:
            route_text = f"{departure_station}->{arrival_station}"
            item_parts.append(route_text)
        elif departure_station:
            item_parts.append(departure_station)
        if train_number:
            item_parts.append(train_number)
        if seat_type:
            item_parts.append(seat_type)
        if seat_number:
            item_parts.append(seat_number)
        if departure_time:
            item_parts.append(f"{departure_time}开")

        item_name = None
        if item_parts:
            item_name = ("铁路电子客票 " + " ".join(item_parts)).strip()[:255]

        return {
            "company_name": company_name,
            "tax_id": tax_id,
            "invoice_number": invoice_number,
            "issue_date": self._extract_issue_date(text),
            "item_name": item_name,
            "total_amount": total_amount,
            "ticket_number": ticket_number,
            "departure_station": departure_station,
            "arrival_station": arrival_station,
            "train_number": train_number,
            "travel_date": self._parse_date_text(travel_date_text) if travel_date_text else None,
            "departure_time": departure_time,
            "seat_type": seat_type,
            "seat_number": seat_number,
            "passenger_name": passenger_name,
        }

    def _extract_railway_stations(self, text: str) -> list[str]:
        stations: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"([\u4e00-\u9fff]{2,20}站)", text):
            station = match.group(1)
            if station in seen:
                continue
            seen.add(station)
            stations.append(station)
        return stations

    def _extract_railway_passenger_name(self, text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        id_like_line = re.compile(r"\d{6,}\*{2,}[0-9Xx]{2,}")
        for idx, line in enumerate(lines):
            if not id_like_line.search(line):
                continue
            for candidate in lines[idx + 1 : idx + 3]:
                if re.fullmatch(r"[\u4e00-\u9fff]{2,10}", candidate):
                    return candidate
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

    def _parse_amount(self, raw: str) -> Decimal | None:
        cleaned = (raw or "").replace("¥", "").replace("￥", "").replace(",", "").replace(" ", "").strip()
        if not cleaned:
            return None
        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            return None
        if value < 0:
            return None
        return value

    def _extract_amount(self, text: str) -> str | None:
        money_pattern = re.compile(r"([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)")
        candidates: list[tuple[int, Decimal]] = []

        for pattern, score in [
            (r"价税合计\s*(?:\([^)]*小写[^)]*\))?\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", 120),
            (r"\(小写\)\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", 110),
            (r"总金额\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", 100),
            (r"金额合计\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", 95),
            (r"票价\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", 95),
            (r"合计\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", 80),
            (r"总计\s*[:：]?\s*([¥￥]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", 80),
        ]:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                parsed = self._parse_amount(match.group(1))
                if parsed is not None:
                    candidates.append((score, parsed))

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            line_score = 0
            if any(k in stripped for k in ["价税合计", "小写"]):
                line_score = 90
            elif any(k in stripped for k in ["总金额", "金额合计", "票价", "合计", "总计"]):
                line_score = 70
            elif "¥" in stripped or "￥" in stripped:
                line_score = 45

            if line_score <= 0:
                continue

            for match in money_pattern.finditer(stripped):
                parsed = self._parse_amount(match.group(1))
                if parsed is not None:
                    candidates.append((line_score, parsed))

        if not candidates:
            return None

        best_score = max(score for score, _ in candidates)
        best_values = [value for score, value in candidates if score == best_score]
        return str(max(best_values).quantize(Decimal("0.01")))


ocr_service = InvoiceOCRService()
