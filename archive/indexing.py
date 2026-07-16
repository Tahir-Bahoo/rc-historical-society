"""PDF text extraction and indexing for full-text search.

Heavy work must run in a separate process (``process_index_queue``), never
inside a Gunicorn worker — large PDFs can OOM the whole EC2 instance.
"""

from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import pymupdf  # PyMuPDF

from .models import Document, PDFPage

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50


@contextmanager
def _open_pdf_path(document: Document) -> Iterator[Path | None]:
    """Yield a local filesystem path for the document PDF.

    Supports uploaded local files, legacy paths, and S3 (downloads to a temp file).
    """
    if document.pdf_file and document.pdf_file.name:
        # Local FileSystemStorage exposes .path; S3 storage does not.
        try:
            local_path = Path(document.pdf_file.path)
            if local_path.exists():
                yield local_path
                return
        except (NotImplementedError, ValueError, AttributeError):
            pass

        suffix = Path(document.pdf_file.name).suffix or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            for chunk in document.pdf_file.chunks(chunk_size=1024 * 1024):
                tmp.write(chunk)
            tmp.flush()
            yield Path(tmp.name)
            return

    if document.pdf_file_path:
        legacy = document.pdf_file_path.lstrip("/")
        candidate = Path(settings.LEGACY_ROOT) / legacy
        if candidate.exists():
            yield candidate
            return

    yield None


def _extract_pages(pdf_path: Path) -> Iterator[tuple[int, str]]:
    """Yield (page_number, text) tuples. 1-indexed pages."""
    with pymupdf.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            yield index, page.get_text("text") or ""


def index_document(document: Document) -> int:
    """(Re)build PDFPage rows for a single Document. Returns the page count.

    Idempotent: deletes any existing pages for the document, then re-inserts
    in small batches so a large PDF does not hold every page in RAM at once.
    """
    with _open_pdf_path(document) as pdf_path:
        if not pdf_path:
            logger.warning("Skipping %s: no resolvable PDF path", document)
            return 0

        with transaction.atomic():
            PDFPage.objects.filter(document=document).delete()
            batch: list[PDFPage] = []
            page_count = 0
            for num, text in _extract_pages(pdf_path):
                batch.append(
                    PDFPage(document=document, page_number=num, text=text)
                )
                page_count += 1
                if len(batch) >= _BATCH_SIZE:
                    PDFPage.objects.bulk_create(batch, batch_size=_BATCH_SIZE)
                    batch.clear()
            if batch:
                PDFPage.objects.bulk_create(batch, batch_size=_BATCH_SIZE)

            Document.objects.filter(pk=document.pk).update(
                page_count=page_count, indexed_at=timezone.now()
            )

    logger.info("Indexed %s: %d pages", document, page_count)
    return page_count


def pending_index_queryset():
    """Documents that have a PDF but are not yet indexed for search."""
    from django.db.models import Q

    return (
        Document.objects.filter(indexed_at__isnull=True)
        .filter(Q(pdf_file__gt="") | Q(pdf_file_path__gt=""))
        .order_by("id")
    )


def reindex_all(only_missing: bool = False, limit: int | None = None) -> dict:
    """Reindex documents. Prefer ``only_missing=True`` from the worker."""
    qs = pending_index_queryset() if only_missing else Document.objects.all().order_by("id")
    if limit is not None:
        qs = qs[:limit]

    summary = {"indexed": 0, "skipped": 0, "pages": 0}
    for document in qs.iterator(chunk_size=10):
        try:
            pages = index_document(document)
        except Exception:
            logger.exception("Failed to index document %s", document.pk)
            summary["skipped"] += 1
            continue
        if pages:
            summary["indexed"] += 1
            summary["pages"] += pages
        else:
            summary["skipped"] += 1
    return summary


def queue_document_for_index(document: Document) -> None:
    """Mark a document so the background worker will pick it up."""
    Document.objects.filter(pk=document.pk).update(indexed_at=None, page_count=0)
