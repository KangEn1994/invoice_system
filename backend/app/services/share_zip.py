from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.models import Share


def ensure_share_zip(share: Share, zip_cache_dir: str) -> Path:
    cache_dir = Path(zip_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    zip_path = cache_dir / f"share_{share.id}.zip"
    if zip_path.exists():
        return zip_path

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
        for item in share.items:
            file_path = Path(item.invoice.file_path)
            if file_path.exists():
                # Avoid duplicate names in zip by prefixing invoice id.
                archive_name = f"{item.invoice_id}_{item.invoice.file_name}"
                zf.write(file_path, arcname=archive_name)

    return zip_path
