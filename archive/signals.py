"""Auto-index a Document whenever its PDF file is added or changed.

We use a ``pre_save`` hook to remember the previous file/path, then in
``post_save`` we re-index only if the file actually changed (or the row
is brand new). This keeps the admin snappy when editors edit non-PDF
fields like ``available`` or ``brand``.
"""

from __future__ import annotations

import logging
import threading

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Document

logger = logging.getLogger(__name__)


def _file_signature(doc: Document) -> tuple[str, str]:
    return (doc.pdf_file.name if doc.pdf_file else "", doc.pdf_file_path or "")


@receiver(pre_save, sender=Document)
def _capture_previous_pdf(sender, instance: Document, **kwargs):
    if not instance.pk:
        instance._previous_pdf_signature = ("", "")
        return
    try:
        previous = Document.objects.get(pk=instance.pk)
    except Document.DoesNotExist:
        instance._previous_pdf_signature = ("", "")
        return
    instance._previous_pdf_signature = _file_signature(previous)


def _index_in_background(document_pk: int) -> None:
    """Extract PDF text without blocking the admin HTTP request."""
    from .indexing import index_document

    try:
        document = Document.objects.get(pk=document_pk)
        pages = index_document(document)
        logger.info("Background indexed %s: %d pages", document, pages)
    except Document.DoesNotExist:
        logger.warning("Background indexing skipped: document %s no longer exists", document_pk)
    except Exception:
        logger.exception("Background indexing failed for document %s", document_pk)


@receiver(post_save, sender=Document)
def auto_index_document(sender, instance: Document, created, **kwargs):
    current = _file_signature(instance)
    if current == ("", ""):
        return

    previous = getattr(instance, "_previous_pdf_signature", ("", ""))
    if not created and current == previous:
        return

    instance._indexing_scheduled = True
    document_pk = instance.pk
    transaction.on_commit(
        lambda: threading.Thread(
            target=_index_in_background,
            args=(document_pk,),
            daemon=True,
            name=f"index-pdf-{document_pk}",
        ).start()
    )
