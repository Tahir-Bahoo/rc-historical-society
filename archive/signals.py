"""Queue PDF search indexing — never run heavy extraction inside Gunicorn.

Previously a background thread opened large PDFs inside the web worker. That
could OOM the EC2 instance and leave Nginx returning 502 until restart.

On PDF upload/change we only mark the document as pending. A separate process
(``manage.py process_index_queue``) does the actual indexing.
"""

from __future__ import annotations

import logging

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


@receiver(post_save, sender=Document)
def queue_document_indexing(sender, instance: Document, created, **kwargs):
    current = _file_signature(instance)
    if current == ("", ""):
        return

    previous = getattr(instance, "_previous_pdf_signature", ("", ""))
    if not created and current == previous:
        return

    def _mark_pending():
        from .indexing import queue_document_for_index

        queue_document_for_index(instance)
        instance._indexing_queued = True
        logger.info(
            "Queued document %s for search indexing (worker will process it)",
            instance.pk,
        )

    transaction.on_commit(_mark_pending)
