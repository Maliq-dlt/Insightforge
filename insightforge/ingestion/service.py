from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from insightforge.config import Settings
from insightforge.ingestion.validators import fingerprint, safe_filename, validate_size
from insightforge.profiling.profiler import DatasetProfiler
from insightforge.storage.database import TraceStore


class DatasetService:
    def __init__(self, settings: Settings, store: TraceStore, profiler: DatasetProfiler) -> None:
        self.settings = settings
        self.store = store
        self.profiler = profiler

    def ingest_path(self, source_path: Path, original_name: str | None = None) -> dict[str, Any]:
        name = safe_filename(original_name or source_path.name)
        size_bytes = source_path.stat().st_size
        validate_size(size_bytes, self.settings.max_upload_mb)
        dataset_fingerprint = fingerprint(source_path)
        existing = self.store.find_dataset_by_fingerprint(dataset_fingerprint)
        if existing is not None:
            return existing

        destination = self.settings.dataset_dir / f"ds_{uuid4().hex[:12]}{Path(name).suffix.lower()}"
        shutil.copyfile(source_path, destination)
        try:
            profile = self.profiler.profile(destination)
            return self.store.create_dataset(
                {
                    "name": name,
                    "fingerprint": dataset_fingerprint,
                    "schema": profile["schema"],
                    "profile": profile,
                    "storage_uri": str(destination.resolve()),
                    "size_bytes": size_bytes,
                }
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
