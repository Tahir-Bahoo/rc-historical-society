"""Reindex PDFs (prefer process_index_queue in production)."""

from django.core.management.base import BaseCommand

from archive.indexing import reindex_all


class Command(BaseCommand):
    help = (
        "Extract per-page text from Document PDFs. "
        "On the server, prefer: python manage.py process_index_queue"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Skip documents that already have an indexed_at timestamp.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max documents to process this run.",
        )

    def handle(self, *args, **options):
        summary = reindex_all(
            only_missing=options["only_missing"],
            limit=options["limit"],
        )
        self.stdout.write(self.style.SUCCESS(
            "Indexed {indexed} document(s) covering {pages} page(s). "
            "Skipped {skipped} unresolvable.".format(**summary)
        ))
