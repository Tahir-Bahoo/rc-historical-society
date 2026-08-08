"""Bulk-import a folder tree of PDFs as Document records.

Designed for a one-time (or repeatable) load of the whole archive without
using the admin panel — the admin upload path is what OOM-crashed the small
EC2 instance. This command:

  * walks a local directory (top-level folder = category),
  * uploads each PDF through Django storage (S3 in production),
  * creates one Document per file (idempotent by source path),
  * DOES NOT extract text inline — it leaves ``indexed_at = NULL`` so the
    background worker (``process_index_queue``) indexes them slowly.

Typical usage on the server::

    # 1. Download the Drive folder to ./incoming (see HOSTING.md)
    # 2. Preview what would happen
    python manage.py import_pdfs --source ./incoming --dry-run
    # 3. Do it
    python manage.py import_pdfs --source ./incoming

Map a differently-named folder to a category::

    python manage.py import_pdfs --source ./incoming \
        --map "Radio Race Car=rc_model_cars"
"""

from __future__ import annotations

import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from archive.models import Document

# Normalised folder name -> category. Keys are lowercased, non-alnum stripped.
_CATEGORY_ALIASES = {
    "competitionplus": "competition_plus",
    "revup": "rev_up",
    "rcmodelcars": "rc_model_cars",
    "rcmodelcar": "rc_model_cars",
    "radiocontrolmodelcars": "rc_model_cars",
    "xtremerccars": "xtreme_rc_cars",
    "xtremerccar": "xtreme_rc_cars",
    "raceprogramsandrules": "race_programs_rules",
    "raceprograms": "race_programs_rules",
    "catalogs": "catalogs",
    "catalogues": "catalogs",
    "manuals": "manuals",
}

_MAGAZINE_CATEGORIES = {
    "competition_plus",
    "rev_up",
    "rc_model_cars",
    "xtreme_rc_cars",
}

_MONTH_NAMES = {
    m.lower(): m
    for m in [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
}


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _humanize(stem: str) -> str:
    return re.sub(r"[_\-]+", " ", stem).strip().title() or "Untitled"


def _parse_year_month(stem: str) -> tuple[int, str]:
    year_match = re.search(r"(19|20)\d{2}", stem)
    year = int(year_match.group(0)) if year_match else 0
    month = ""
    for token in re.split(r"[_\-\s]+", stem.lower()):
        if token in _MONTH_NAMES:
            month = _MONTH_NAMES[token]
            break
    return year, month


def _guess_brand(stem: str) -> str:
    first = re.split(r"[_\-]+", stem)[0]
    return first.title() if first else ""


class Command(BaseCommand):
    help = (
        "Bulk-import PDFs from a folder tree into Document records "
        "(uploads to S3, defers indexing to the background worker)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Directory to scan. Each top-level subfolder is a category.",
        )
        parser.add_argument(
            "--map",
            action="append",
            default=[],
            metavar="FOLDER=category",
            help="Force a folder name to a category. Repeatable.",
        )
        parser.add_argument(
            "--default-category",
            default=None,
            help="Category for PDFs not under a recognised folder.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Import at most N new files (useful for a first test run).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without writing anything.",
        )

    def handle(self, *args, **options):
        source = Path(options["source"]).expanduser().resolve()
        if not source.is_dir():
            raise CommandError(f"Source is not a directory: {source}")

        valid = {c for c, _ in Document.CATEGORY_CHOICES}
        overrides = self._parse_overrides(options["map"], valid)
        default_category = options["default_category"]
        if default_category and default_category not in valid:
            raise CommandError(
                f"--default-category '{default_category}' is not one of {sorted(valid)}"
            )

        dry_run = options["dry_run"]
        limit = options["limit"]

        created = existing = skipped = 0
        unmatched_folders: set[str] = set()

        for pdf in sorted(source.rglob("*.pdf")):
            rel = pdf.relative_to(source)
            top_folder = rel.parts[0] if len(rel.parts) > 1 else ""
            category = self._resolve_category(
                top_folder, overrides, default_category
            )
            if category is None:
                unmatched_folders.add(top_folder or "(root)")
                skipped += 1
                continue

            source_key = rel.as_posix()
            if Document.objects.filter(pdf_file_path=source_key).exists():
                existing += 1
                continue

            if limit is not None and created >= limit:
                break

            stem = pdf.stem
            year, month = _parse_year_month(stem)
            defaults = {
                "category": category,
                "publication_name": _humanize(stem),
                "year": year,
                "month": month if category in _MAGAZINE_CATEGORIES else "",
                "available": True,
                # Keep the source path as an idempotency key; indexer prefers pdf_file.
                "pdf_file_path": source_key,
            }
            if category in {"catalogs", "manuals"}:
                defaults["brand"] = _guess_brand(stem)

            size_mb = pdf.stat().st_size / (1024 * 1024)
            self.stdout.write(
                f"  + [{category}] {source_key}  ({size_mb:.1f} MB) -> {defaults['publication_name']}"
            )
            if dry_run:
                created += 1
                continue

            self._create_document(pdf, stem, year, defaults)
            created += 1

        self._report(created, existing, skipped, unmatched_folders, dry_run)

    def _parse_overrides(self, raw_maps, valid) -> dict[str, str]:
        overrides: dict[str, str] = {}
        for item in raw_maps:
            if "=" not in item:
                raise CommandError(f"--map expects FOLDER=category, got: {item!r}")
            folder, category = item.split("=", 1)
            category = category.strip()
            if category not in valid:
                raise CommandError(
                    f"--map category '{category}' is not one of {sorted(valid)}"
                )
            overrides[_normalise(folder)] = category
        return overrides

    def _resolve_category(self, folder, overrides, default_category):
        key = _normalise(folder)
        if key in overrides:
            return overrides[key]
        if key in _CATEGORY_ALIASES:
            return _CATEGORY_ALIASES[key]
        return default_category

    def _create_document(self, pdf: Path, stem: str, year: int, defaults: dict):
        doc = Document(**defaults)
        # Field path (e.g. pdfs/2026/foo.pdf) via the field's upload_to.
        name = doc.pdf_file.field.generate_filename(doc, pdf.name)
        storage = doc.pdf_file.storage

        if hasattr(storage, "bucket"):
            # S3: stream straight from disk with a small, low-concurrency
            # multipart config so a 300 MB PDF never blows up RAM on a tiny box.
            self._upload_to_s3(storage, pdf, name)
            doc.pdf_file.name = name
        else:
            with pdf.open("rb") as fh:
                doc.pdf_file.save(Path(name).name, File(fh), save=False)

        # indexed_at stays NULL -> background worker will index it.
        doc.save()

    def _upload_to_s3(self, storage, pdf: Path, name: str):
        from boto3.s3.transfer import TransferConfig

        location = getattr(storage, "location", "") or ""
        key = f"{location.rstrip('/')}/{name}" if location else name
        key = key.lstrip("/")
        # ~16 MB peak (2 x 8 MB parts) instead of loading the whole file.
        config = TransferConfig(
            multipart_threshold=8 * 1024 * 1024,
            multipart_chunksize=8 * 1024 * 1024,
            max_concurrency=2,
            use_threads=True,
        )
        storage.bucket.upload_file(
            str(pdf),
            key,
            ExtraArgs={"ContentType": "application/pdf"},
            Config=config,
        )

    def _report(self, created, existing, skipped, unmatched, dry_run):
        prefix = "DRY RUN — " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Imported {created} new, {existing} already present, "
            f"{skipped} skipped."
        ))
        if unmatched:
            self.stdout.write(self.style.WARNING(
                "Unmatched folders (use --map or --default-category): "
                + ", ".join(sorted(unmatched))
            ))
        if not dry_run and created:
            self.stdout.write(
                "Search indexing will run via: python manage.py process_index_queue "
                "(or the rchs-index Supervisor worker)."
            )
