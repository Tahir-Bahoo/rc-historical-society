"""Walk the legacy PHP site and register every PDF as a Document.

Usage::

    python manage.py seed_legacy_pdfs           # add new ones only
    python manage.py seed_legacy_pdfs --reindex # add new ones AND reindex everything

Files are NOT copied; legacy paths are stored on ``Document.pdf_file_path``
and resolved against ``settings.LEGACY_ROOT`` at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from archive.indexing import index_document, reindex_all
from archive.models import Document

CATEGORY_FOLDERS = {
    "competition_plus": ("competition-plus", "Competition Plus"),
    "rev_up": ("rev-up", "Rev-Up"),
    "rc_model_cars": ("rc_model_cars", "R/C Model Cars"),
    "xtreme_rc_cars": ("xtreme_rc_cars", "Xtreme RC Cars"),
    "race_programs_rules": ("race_programs_and_rules", "Race Programs and Rules"),
    "catalogs": ("catalogs", "Catalogs"),
    "manuals": ("manuals", "Manuals"),
}

MONTH_NAMES = {
    m.lower(): m
    for m in [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
}


def _humanize(stem: str) -> str:
    return re.sub(r"[_\-]+", " ", stem).strip().title()


def _parse_magazine_filename(stem: str) -> tuple[int | None, str]:
    """Try to extract (year, month) from a magazine filename."""
    year_match = re.search(r"(19|20)\d{2}", stem)
    year = int(year_match.group(0)) if year_match else None
    month = ""
    for token in re.split(r"[_\-\s]+", stem.lower()):
        if token in MONTH_NAMES:
            month = MONTH_NAMES[token]
            break
    return year, month


def _guess_brand(stem: str) -> str:
    """First underscore-separated token, title-cased, as a rough brand."""
    first = re.split(r"[_\-]+", stem)[0]
    return first.title() if first else ""


class Command(BaseCommand):
    help = "Discover legacy PDFs under LEGACY_ROOT and register them as Documents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reindex",
            action="store_true",
            help="Also extract text for every PDF (existing + new).",
        )

    def handle(self, *args, **options):
        legacy_root = Path(settings.LEGACY_ROOT)
        created, existing = 0, 0

        for category, (folder, _label) in CATEGORY_FOLDERS.items():
            base = legacy_root / folder
            if not base.exists():
                self.stdout.write(self.style.WARNING(f"  - skip missing folder: {folder}"))
                continue

            for pdf in sorted(base.rglob("*.pdf")):
                rel_path = pdf.relative_to(legacy_root).as_posix()
                stem = pdf.stem

                defaults = {"category": category, "available": True}
                is_magazine = category in {
                    "competition_plus",
                    "rev_up",
                    "rc_model_cars",
                    "xtreme_rc_cars",
                }
                if is_magazine:
                    year, month = _parse_magazine_filename(stem)
                    defaults["publication_name"] = _humanize(stem)
                    defaults["year"] = year or 0
                    defaults["month"] = month
                else:
                    defaults["publication_name"] = _humanize(stem)
                    year_match = re.search(r"(19|20)\d{2}", stem)
                    defaults["year"] = int(year_match.group(0)) if year_match else 0
                    if category in {"catalogs", "manuals"}:
                        defaults["brand"] = _guess_brand(stem)

                doc, was_created = Document.objects.get_or_create(
                    pdf_file_path=rel_path,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                    self.stdout.write(f"  + {category}: {rel_path}")
                    if options["reindex"]:
                        index_document(doc)
                else:
                    existing += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created} new Document(s), {existing} already existed."
        ))

        if options["reindex"]:
            summary = reindex_all()
            self.stdout.write(self.style.SUCCESS(
                "Reindex complete: {indexed} indexed, {pages} pages, {skipped} skipped.".format(**summary)
            ))
