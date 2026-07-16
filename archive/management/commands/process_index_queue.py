"""Background worker: index PDFs that are pending search indexing.

Run as a separate Supervisor/systemd process so large PDFs never share
memory with Gunicorn (that caused 502 / instance crashes).

Examples::

    # One-shot (cron or manual)
    python manage.py process_index_queue --limit 5

    # Long-running worker (recommended in production)
    python manage.py process_index_queue --loop --sleep 15
"""

from __future__ import annotations

import gc
import time

from django.core.management.base import BaseCommand

from archive.indexing import index_document, pending_index_queryset


class Command(BaseCommand):
    help = (
        "Index pending Document PDFs for search. Safe to run alongside "
        "Gunicorn — use --loop under Supervisor."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max documents to process this run (default: all pending).",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep running and poll for new pending documents.",
        )
        parser.add_argument(
            "--sleep",
            type=int,
            default=15,
            help="Seconds to sleep between polls when --loop (default: 15).",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        loop = options["loop"]
        sleep_seconds = max(1, options["sleep"])

        if loop:
            self.stdout.write(
                self.style.NOTICE(
                    f"Index worker started (poll every {sleep_seconds}s). Ctrl+C to stop."
                )
            )
            while True:
                self._process_batch(limit=1)
                time.sleep(sleep_seconds)
        else:
            summary = self._process_batch(limit=limit)
            self.stdout.write(
                self.style.SUCCESS(
                    "Indexed {indexed} document(s) ({pages} pages). "
                    "Skipped {skipped}.".format(**summary)
                )
            )

    def _process_batch(self, limit: int | None) -> dict:
        qs = pending_index_queryset()
        if limit is not None:
            qs = qs[:limit]

        summary = {"indexed": 0, "skipped": 0, "pages": 0}
        # Materialize IDs first so the queryset is not held open during indexing
        ids = list(qs.values_list("id", flat=True))
        for doc_id in ids:
            from archive.models import Document

            try:
                document = Document.objects.get(pk=doc_id)
            except Document.DoesNotExist:
                summary["skipped"] += 1
                continue

            self.stdout.write(f"Indexing document {doc_id}: {document} …")
            try:
                pages = index_document(document)
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f"Failed document {doc_id}: {exc}")
                )
                summary["skipped"] += 1
            else:
                if pages:
                    summary["indexed"] += 1
                    summary["pages"] += pages
                    self.stdout.write(
                        self.style.SUCCESS(f"  → {pages} page(s)")
                    )
                else:
                    summary["skipped"] += 1
                    self.stdout.write(
                        self.style.WARNING("  → skipped (no readable PDF)")
                    )
            finally:
                gc.collect()

        return summary
