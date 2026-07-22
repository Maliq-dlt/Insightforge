from __future__ import annotations

import hashlib
from pathlib import Path

SUPPORTED_EXTENSIONS = {".csv", ".parquet"}


class DatasetValidationError(ValueError):
    pass


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name or name in {".", ".."}:
        raise DatasetValidationError("Nama file tidak valid.")
    if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise DatasetValidationError("Format harus CSV atau Parquet.")
    return name


def validate_size(size_bytes: int, max_upload_mb: int) -> None:
    if size_bytes <= 0:
        raise DatasetValidationError("File kosong.")
    if size_bytes > max_upload_mb * 1024 * 1024:
        raise DatasetValidationError(f"Ukuran file melebihi {max_upload_mb} MB.")


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
