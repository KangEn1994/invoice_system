from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.models import Share
from app.services.file_naming import build_invoice_download_name


def ensure_share_zip(share: Share, zip_cache_dir: str) -> Path:
    cache_dir = Path(zip_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    zip_path = cache_dir / f"share_{share.id}.zip"
    if zip_path.exists():
        zip_path.unlink()

    used_names: set[str] = set()
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
        for item in share.items:
            file_path = Path(item.invoice.file_path)
            if file_path.exists():
                original_name = build_invoice_download_name(item.invoice)
                stem = Path(original_name).stem
                suffix = Path(original_name).suffix
                archive_name = original_name
                index = 2
                while archive_name in used_names:
                    archive_name = f"{stem}_{index}{suffix}"
                    index += 1
                used_names.add(archive_name)
                zf.write(file_path, arcname=archive_name)

    return zip_path
