"""PDF text extraction and indexing for full-text search.

We open the PDF with PyMuPDF, extract per-page plain text, and upsert
``PDFPage`` rows. The FastAPI service later queries those rows.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.db import transaction
from django.utils import timezone

import pymupdf  # PyMuPDF

from .models import Document, PDFPage

logger = logging.getLogger(__name__)


def _extract_pages(pdf_path) -> Iterable[tuple[int, str]]:
    """Yield (page_number, text) tuples for each page. 1-indexed pages."""
    with pymupdf.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            yield index, page.get_text("text") or ""


@transaction.atomic
def index_document(document: Document) -> int:
    """(Re)build PDFPage rows for a single Document. Returns the page count.

    Idempotent: deletes any existing pages for the document, then re-inserts.
    """
    pdf_path = document.resolve_pdf_filesystem_path()
    if not pdf_path:
        logger.warning("Skipping %s: no resolvable PDF path", document)
        return 0

    PDFPage.objects.filter(document=document).delete()
    pages = [
        PDFPage(document=document, page_number=num, text=text)
        for num, text in _extract_pages(pdf_path)
    ]
    PDFPage.objects.bulk_create(pages, batch_size=200)

    Document.objects.filter(pk=document.pk).update(
        page_count=len(pages), indexed_at=timezone.now()
    )
    logger.info("Indexed %s: %d pages", document, len(pages))
    return len(pages)


def reindex_all(only_missing: bool = False) -> dict:
    """Reindex every Document. Returns a summary dict."""
    qs = Document.objects.all()
    if only_missing:
        qs = qs.filter(indexed_at__isnull=True)

    summary = {"indexed": 0, "skipped": 0, "pages": 0}
    for document in qs.iterator():
        pages = index_document(document)
        if pages:
            summary["indexed"] += 1
            summary["pages"] += pages
        else:
            summary["skipped"] += 1
    return summary
