from __future__ import annotations

import os
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.deps import get_current_admin
from app.models import AdminUser, Invoice, Share, ShareAccessLog, ShareItem, invoice_tags
from app.schemas import (
    ShareCreateByFiltersRequest,
    ShareCreateRequest,
    ShareCreateResponse,
    ShareListItem,
    ShareListResponse,
    ShareLogListResponse,
    ShareLogOut,
    ShareOut,
)
from app.services.file_naming import build_invoice_download_name
from app.services.share_zip import ensure_share_zip


router = APIRouter(prefix="/shares", tags=["shares"])
log_router = APIRouter(prefix="/share-logs", tags=["share-logs"])


def _share_url(token: str) -> str:
    return f"{settings.public_share_base_url.rstrip('/')}/share.html?token={token}"


def _apply_invoice_filters(
    query: Select,
    *,
    q: str | None,
    company_name: str | None,
    invoice_number: str | None,
    tax_id: str | None,
    date_from: date | None,
    date_to: date | None,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
    ocr_status: str | None,
) -> Select:
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


def _create_share_with_invoice_ids(db: Session, *, title: str, invoice_ids: list[int]) -> ShareCreateResponse:
    unique_ids = list(dict.fromkeys(invoice_ids))
    invoices = db.scalars(select(Invoice.id).where(Invoice.id.in_(unique_ids))).all()
    if len(invoices) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invoice_ids 包含不存在的发票")

    share = Share(title=title, token=secrets.token_urlsafe(32), status="active")
    db.add(share)
    db.flush()

    for invoice_id in unique_ids:
        db.add(ShareItem(share_id=share.id, invoice_id=invoice_id))

    db.commit()
    db.refresh(share)

    return ShareCreateResponse(
        id=share.id,
        title=share.title,
        token=share.token,
        status=share.status,
        created_at=share.created_at,
        revoked_at=share.revoked_at,
        share_url=_share_url(share.token),
        item_count=len(unique_ids),
    )


def _log_share_access(
    db: Session,
    *,
    share_id: int,
    action: str,
    status_code: int,
    request: Request | None,
    invoice_id: int | None = None,
) -> None:
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None

    log = ShareAccessLog(
        share_id=share_id,
        invoice_id=invoice_id,
        action=action,
        ip=ip,
        user_agent=ua,
        status_code=status_code,
    )
    db.add(log)
    db.commit()


@router.post("", response_model=ShareCreateResponse, status_code=status.HTTP_201_CREATED)
def create_share(
    payload: ShareCreateRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> ShareCreateResponse:
    return _create_share_with_invoice_ids(
        db=db,
        title=payload.title,
        invoice_ids=payload.invoice_ids,
    )


@router.post("/from-filters", response_model=ShareCreateResponse, status_code=status.HTTP_201_CREATED)
def create_share_from_filters(
    payload: ShareCreateByFiltersRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> ShareCreateResponse:
    query = select(Invoice.id)
    query = _apply_invoice_filters(
        query,
        q=payload.q,
        company_name=payload.company_name,
        invoice_number=payload.invoice_number,
        tax_id=payload.tax_id,
        date_from=payload.date_from,
        date_to=payload.date_to,
        amount_min=payload.amount_min,
        amount_max=payload.amount_max,
        ocr_status=payload.ocr_status,
    )
    if payload.tag_ids:
        query = query.join(invoice_tags, invoice_tags.c.invoice_id == Invoice.id).where(
            invoice_tags.c.tag_id.in_(payload.tag_ids)
        )

    invoice_ids = db.scalars(query.distinct().order_by(Invoice.id.asc())).all()
    if not invoice_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前筛选条件没有可分享的发票")

    return _create_share_with_invoice_ids(
        db=db,
        title=payload.title,
        invoice_ids=list(invoice_ids),
    )


@router.get("", response_model=ShareListResponse)
def list_shares(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> ShareListResponse:
    count_subq = (
        select(ShareItem.share_id, func.count(ShareItem.id).label("item_count"))
        .group_by(ShareItem.share_id)
        .subquery()
    )

    query = select(Share, func.coalesce(count_subq.c.item_count, 0)).outerjoin(
        count_subq, count_subq.c.share_id == Share.id
    )

    if status_filter:
        query = query.where(Share.status == status_filter)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    query = query.order_by(Share.created_at.desc(), Share.id.desc())
    offset = (page - 1) * page_size

    rows = db.execute(query.offset(offset).limit(page_size)).all()

    items = [
        ShareListItem(
            id=row[0].id,
            title=row[0].title,
            token=row[0].token,
            status=row[0].status,
            item_count=int(row[1] or 0),
            created_at=row[0].created_at,
            revoked_at=row[0].revoked_at,
        )
        for row in rows
    ]

    return ShareListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/{share_id}")
def get_share_detail(
    share_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    share = db.scalar(
        select(Share)
        .options(selectinload(Share.items).selectinload(ShareItem.invoice))
        .where(Share.id == share_id)
    )
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享不存在")

    items = []
    for item in share.items:
        invoice = item.invoice
        items.append(
            {
                "invoice_id": item.invoice_id,
                "file_name": build_invoice_download_name(invoice),
                "company_name": invoice.company_name,
                "invoice_number": invoice.invoice_number,
                "issue_date": invoice.issue_date,
                "total_amount": invoice.total_amount,
            }
        )

    return {
        "id": share.id,
        "title": share.title,
        "token": share.token,
        "status": share.status,
        "created_at": share.created_at,
        "revoked_at": share.revoked_at,
        "share_url": _share_url(share.token),
        "item_count": len(items),
        "items": items,
    }


@router.post("/{share_id}/revoke", response_model=ShareOut)
def revoke_share(
    share_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> ShareOut:
    share = db.get(Share, share_id)
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享不存在")

    if share.status != "revoked":
        share.status = "revoked"
        share.revoked_at = datetime.now(timezone.utc)
        db.add(share)
        db.commit()
        cache_file = Path(settings.zip_cache_dir) / f"share_{share.id}.zip"
        if cache_file.exists():
            os.remove(cache_file)
    db.refresh(share)

    return share


@router.delete(
    "/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_share(
    share_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> Response:
    share = db.get(Share, share_id)
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享不存在")

    cache_file = Path(settings.zip_cache_dir) / f"share_{share.id}.zip"
    if cache_file.exists():
        os.remove(cache_file)

    db.delete(share)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@log_router.get("", response_model=ShareLogListResponse)
def list_share_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    share_id: int | None = None,
    action: str | None = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> ShareLogListResponse:
    query = select(ShareAccessLog)
    if share_id is not None:
        query = query.where(ShareAccessLog.share_id == share_id)
    if action:
        query = query.where(ShareAccessLog.action == action)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    query = query.order_by(ShareAccessLog.created_at.desc(), ShareAccessLog.id.desc())

    offset = (page - 1) * page_size
    items = db.scalars(query.offset(offset).limit(page_size)).all()

    return ShareLogListResponse(
        items=[ShareLogOut.model_validate(item, from_attributes=True) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


public_router = APIRouter(tags=["public"])


@public_router.get("/s/{token}")
def get_public_share(token: str, request: Request, db: Session = Depends(get_db)):
    share = db.scalar(
        select(Share)
        .options(selectinload(Share.items).selectinload(ShareItem.invoice))
        .where(Share.token == token)
    )
    if not share or share.status != "active":
        if share:
            _log_share_access(db, share_id=share.id, action="view", status_code=404, request=request)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享不存在或已失效")

    items = [
        {
            "invoice_id": item.invoice_id,
            "file_name": build_invoice_download_name(item.invoice),
            "company_name": item.invoice.company_name,
            "invoice_number": item.invoice.invoice_number,
            "issue_date": item.invoice.issue_date,
            "total_amount": item.invoice.total_amount,
        }
        for item in share.items
    ]

    _log_share_access(db, share_id=share.id, action="view", status_code=200, request=request)
    return {"title": share.title, "items": items}


@public_router.get("/s/{token}/file/{invoice_id}")
def public_download_file(token: str, invoice_id: int, request: Request, db: Session = Depends(get_db)):
    share = db.scalar(
        select(Share)
        .options(selectinload(Share.items).selectinload(ShareItem.invoice))
        .where(Share.token == token)
    )
    if not share or share.status != "active":
        if share:
            _log_share_access(db, share_id=share.id, action="file", status_code=404, request=request, invoice_id=invoice_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享不存在或已失效")

    target = next((item.invoice for item in share.items if item.invoice_id == invoice_id), None)
    if not target:
        _log_share_access(db, share_id=share.id, action="file", status_code=404, request=request, invoice_id=invoice_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发票不在分享中")

    if not Path(target.file_path).exists():
        _log_share_access(db, share_id=share.id, action="file", status_code=404, request=request, invoice_id=invoice_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    _log_share_access(db, share_id=share.id, action="file", status_code=200, request=request, invoice_id=invoice_id)
    return FileResponse(
        path=target.file_path,
        filename=build_invoice_download_name(target),
        media_type=target.mime_type,
    )


@public_router.get("/s/{token}/zip")
def public_download_zip(token: str, request: Request, db: Session = Depends(get_db)):
    share = db.scalar(
        select(Share)
        .options(selectinload(Share.items).selectinload(ShareItem.invoice))
        .where(Share.token == token)
    )
    if not share or share.status != "active":
        if share:
            _log_share_access(db, share_id=share.id, action="zip", status_code=404, request=request)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享不存在或已失效")

    zip_path = ensure_share_zip(share, settings.zip_cache_dir)
    _log_share_access(db, share_id=share.id, action="zip", status_code=200, request=request)

    return FileResponse(path=zip_path, filename=f"share_{share.id}.zip", media_type="application/zip")
