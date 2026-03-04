from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.deps import get_current_admin
from app.models import AdminUser, Invoice, Tag, invoice_tags
from app.schemas import BatchSetInvoiceTagsRequest, InvoiceOut, InvoiceUpdate, PaginatedInvoices, SetInvoiceTagsRequest
from app.services.invoice_ocr import ocr_service


router = APIRouter(prefix="/invoices", tags=["invoices"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def _parse_tag_ids(tag_ids: str | None) -> list[int]:
    if not tag_ids:
        return []
    result: list[int] = []
    for part in tag_ids.split(","):
        text = part.strip()
        if text:
            result.append(int(text))
    return result


def _apply_filters(query: Select, *, q: str | None, company_name: str | None, invoice_number: str | None, tax_id: str | None,
                   date_from: date | None, date_to: date | None, amount_min: Decimal | None, amount_max: Decimal | None,
                   ocr_status: str | None) -> Select:
    conditions = []
    if q:
        like = f"%{q}%"
        conditions.append(
            (Invoice.company_name.ilike(like))
            | (Invoice.invoice_number.ilike(like))
            | (Invoice.tax_id.ilike(like))
            | (Invoice.item_name.ilike(like))
        )
    if company_name:
        conditions.append(Invoice.company_name.ilike(f"%{company_name}%"))
    if invoice_number:
        conditions.append(Invoice.invoice_number.ilike(f"%{invoice_number}%"))
    if tax_id:
        conditions.append(Invoice.tax_id.ilike(f"%{tax_id}%"))
    if date_from:
        conditions.append(Invoice.issue_date >= date_from)
    if date_to:
        conditions.append(Invoice.issue_date <= date_to)
    if amount_min is not None:
        conditions.append(Invoice.total_amount >= amount_min)
    if amount_max is not None:
        conditions.append(Invoice.total_amount <= amount_max)
    if ocr_status:
        conditions.append(Invoice.ocr_status == ocr_status)

    if conditions:
        query = query.where(and_(*conditions))
    return query


def _set_invoice_tags(db: Session, invoice: Invoice, tag_ids: list[int]) -> None:
    if not tag_ids:
        invoice.tags = []
        return
    tags = db.scalars(select(Tag).where(Tag.id.in_(tag_ids))).all()
    invoice.tags = list(tags)


def _refresh_invoice(db: Session, invoice_id: int) -> Invoice:
    invoice = db.scalar(select(Invoice).options(selectinload(Invoice.tags)).where(Invoice.id == invoice_id))
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在")
    return invoice


@router.post("", response_model=InvoiceOut)
async def upload_invoice(
    file: UploadFile = File(...),
    auto_ocr: bool = Form(True),
    tag_ids: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> InvoiceOut:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="仅支持 jpg/png/pdf")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="空文件")

    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = Path(settings.files_dir) / saved_name
    saved_path.write_bytes(content)

    invoice = Invoice(
        file_name=file.filename or saved_name,
        file_path=str(saved_path),
        file_ext=ext,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        ocr_status="pending",
    )

    if auto_ocr:
        ocr_result = ocr_service.run(str(saved_path))
        invoice.ocr_status = ocr_result["status"]
        fields = ocr_result.get("fields", {})
        invoice.company_name = fields.get("company_name")
        invoice.tax_id = fields.get("tax_id")
        invoice.invoice_number = fields.get("invoice_number")

        issue_date = fields.get("issue_date")
        if issue_date:
            invoice.issue_date = date.fromisoformat(issue_date)

        invoice.item_name = fields.get("item_name")

        total_amount = fields.get("total_amount")
        if total_amount:
            invoice.total_amount = Decimal(total_amount)

        invoice.ocr_raw = ocr_result.get("raw")

    db.add(invoice)
    db.flush()

    ids = _parse_tag_ids(tag_ids)
    _set_invoice_tags(db, invoice, ids)

    db.commit()

    return _refresh_invoice(db, invoice.id)


@router.post("/{invoice_id}/ocr", response_model=InvoiceOut)
def rerun_ocr(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> InvoiceOut:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在")

    ocr_result = ocr_service.run(invoice.file_path)
    invoice.ocr_status = ocr_result["status"]

    fields = ocr_result.get("fields", {})
    invoice.company_name = fields.get("company_name")
    invoice.tax_id = fields.get("tax_id")
    invoice.invoice_number = fields.get("invoice_number")

    issue_date = fields.get("issue_date")
    invoice.issue_date = date.fromisoformat(issue_date) if issue_date else None

    invoice.item_name = fields.get("item_name")

    total_amount = fields.get("total_amount")
    invoice.total_amount = Decimal(total_amount) if total_amount else None

    invoice.ocr_raw = ocr_result.get("raw")

    db.add(invoice)
    db.commit()

    return _refresh_invoice(db, invoice.id)


@router.get("", response_model=PaginatedInvoices)
def list_invoices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    q: str | None = None,
    company_name: str | None = None,
    invoice_number: str | None = None,
    tax_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    tag_ids: str | None = None,
    ocr_status: str | None = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> PaginatedInvoices:
    query = select(Invoice).options(selectinload(Invoice.tags))
    query = _apply_filters(
        query,
        q=q,
        company_name=company_name,
        invoice_number=invoice_number,
        tax_id=tax_id,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        ocr_status=ocr_status,
    )

    parsed_tag_ids = _parse_tag_ids(tag_ids)
    if parsed_tag_ids:
        query = query.join(invoice_tags, invoice_tags.c.invoice_id == Invoice.id).where(invoice_tags.c.tag_id.in_(parsed_tag_ids))

    query = query.distinct()

    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    sort_columns = {
        "created_at": Invoice.created_at,
        "issue_date": Invoice.issue_date,
        "total_amount": Invoice.total_amount,
    }
    sort_column = sort_columns.get(sort_by, Invoice.created_at)
    if sort_order == "asc":
        query = query.order_by(sort_column.asc().nullslast(), Invoice.id.asc())
    else:
        query = query.order_by(sort_column.desc().nullslast(), Invoice.id.desc())

    offset = (page - 1) * page_size
    items = db.scalars(query.offset(offset).limit(page_size)).unique().all()

    return PaginatedInvoices(items=items, page=page, page_size=page_size, total=total)


@router.post("/batch/tags", response_model=dict)
def batch_set_invoice_tags(
    payload: BatchSetInvoiceTagsRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> dict:
    invoice_ids = list(dict.fromkeys(payload.invoice_ids))
    invoices = db.scalars(select(Invoice).where(Invoice.id.in_(invoice_ids))).all()
    if len(invoices) != len(invoice_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invoice_ids 包含不存在的发票")

    tags = db.scalars(select(Tag).where(Tag.id.in_(payload.tag_ids))).all() if payload.tag_ids else []
    if payload.tag_ids and len(tags) != len(set(payload.tag_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tag_ids 包含不存在的标签")

    for invoice in invoices:
        invoice.tags = list(tags)
        db.add(invoice)

    db.commit()
    return {"updated_count": len(invoices)}


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> InvoiceOut:
    return _refresh_invoice(db, invoice_id)


@router.patch("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> InvoiceOut:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(invoice, key, value)

    db.add(invoice)
    db.commit()

    return _refresh_invoice(db, invoice_id)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> None:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在")

    file_path = invoice.file_path
    db.delete(invoice)
    db.commit()

    if file_path and os.path.exists(file_path):
        os.remove(file_path)


@router.get("/{invoice_id}/file")
def download_invoice_file(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在")

    if not Path(invoice.file_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    return FileResponse(path=invoice.file_path, filename=invoice.file_name, media_type=invoice.mime_type)


@router.put("/{invoice_id}/tags", response_model=InvoiceOut)
def set_invoice_tags(
    invoice_id: int,
    payload: SetInvoiceTagsRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> InvoiceOut:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不存在")

    _set_invoice_tags(db, invoice, payload.tag_ids)
    db.add(invoice)
    db.commit()

    return _refresh_invoice(db, invoice_id)
