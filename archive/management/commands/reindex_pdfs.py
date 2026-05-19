"""Reindex all PDFs (or only ones that have never been indexed)."""

from django.core.management.base import BaseCommand

from archive.indexing import reindex_all


class Command(BaseCommand):
    help = "Extract per-page text from every Document's PDF and upsert PDFPage rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Skip documents that already have an indexed_at timestamp.",
        )

    def handle(self, *args, **options):
        summary = reindex_all(only_missing=options["only_missing"])
        self.stdout.write(self.style.SUCCESS(
            "Indexed {indexed} document(s) covering {pages} page(s). "
            "Skipped {skipped} unresolvable.".format(**summary)
        ))
