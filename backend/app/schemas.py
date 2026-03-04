from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class AdminMeResponse(BaseModel):
    id: int
    username: str
    role: str = "admin"


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class InvoiceUpdate(BaseModel):
    company_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=64)
    invoice_number: str | None = Field(default=None, max_length=64)
    issue_date: date | None = None
    item_name: str | None = Field(default=None, max_length=255)
    total_amount: Decimal | None = None


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    file_ext: str
    file_size: int
    mime_type: str

    ocr_status: str
    company_name: str | None
    tax_id: str | None
    invoice_number: str | None
    issue_date: date | None
    item_name: str | None
    total_amount: Decimal | None
    ocr_raw: dict | None = None

    tags: list[TagOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PaginatedInvoices(BaseModel):
    items: list[InvoiceOut]
    page: int
    page_size: int
    total: int


class SetInvoiceTagsRequest(BaseModel):
    tag_ids: list[int]


class BatchSetInvoiceTagsRequest(BaseModel):
    invoice_ids: list[int] = Field(min_length=1)
    tag_ids: list[int]


class ShareCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    invoice_ids: list[int] = Field(min_length=1)


class ShareCreateByFiltersRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    q: str | None = None
    company_name: str | None = None
    invoice_number: str | None = None
    tax_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    tag_ids: list[int] = Field(default_factory=list)
    ocr_status: str | None = None


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    token: str
    status: str
    created_at: datetime
    revoked_at: datetime | None


class ShareCreateResponse(ShareOut):
    share_url: str
    item_count: int


class ShareListItem(BaseModel):
    id: int
    title: str
    token: str
    status: str
    item_count: int
    created_at: datetime
    revoked_at: datetime | None


class ShareListResponse(BaseModel):
    items: list[ShareListItem]
    page: int
    page_size: int
    total: int


class ShareInvoicePublicItem(BaseModel):
    invoice_id: int
    file_name: str
    company_name: str | None
    invoice_number: str | None
    issue_date: date | None
    total_amount: Decimal | None


class PublicShareResponse(BaseModel):
    title: str
    items: list[ShareInvoicePublicItem]


class ShareLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    share_id: int
    invoice_id: int | None
    action: str
    ip: str | None
    user_agent: str | None
    status_code: int
    created_at: datetime


class ShareLogListResponse(BaseModel):
    items: list[ShareLogOut]
    page: int
    page_size: int
    total: int
