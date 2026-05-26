from pathlib import Path

from django.conf import settings
from django.db import models
from django.templatetags.static import static


class HomepagePost(models.Model):
    date = models.DateField()
    image = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    linked_page = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} - {self.title}"

    @property
    def image_url(self):
        if not self.image:
            return ""
        image_path = self.image[1:] if self.image.startswith("/") else self.image
        return static(image_path)


class Document(models.Model):
    CATEGORY_CHOICES = [
        ("competition_plus", "Competition Plus"),
        ("rev_up", "Rev-Up"),
        ("rc_model_cars", "RC Model Cars"),
        ("xtreme_rc_cars", "Xtreme RC Cars"),
        ("race_programs_rules", "Race Programs and Rules"),
        ("catalogs", "Catalogs"),
        ("manuals", "Manuals"),
    ]
    publication_name = models.CharField(max_length=200)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    year = models.PositiveIntegerField()
    month = models.CharField(max_length=30, blank=True)
    pdf_file = models.FileField(upload_to="pdfs/%Y/", blank=True, null=True)
    pdf_file_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Legacy/external PDF path. Used when no file is uploaded.",
    )
    available = models.BooleanField(default=True)
    brand = models.CharField(max_length=120, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    page_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["category", "year", "month", "publication_name"]

    def __str__(self):
        return f"{self.publication_name} ({self.year} {self.month})"

    @property
    def pdf_url(self):
        """URL to use in templates. Prefers uploaded file, falls back to legacy path."""
        if self.pdf_file:
            return self.pdf_file.url
        return self.pdf_file_path or ""

    def resolve_pdf_filesystem_path(self):
        """Return an absolute filesystem path to the PDF, or None if unresolvable.

        Used by the indexer. Uploaded files live under MEDIA_ROOT; legacy paths
        are resolved relative to the legacy site root (one level above BASE_DIR).
        """
        if self.pdf_file and self.pdf_file.name:
            return Path(self.pdf_file.path)
        if not self.pdf_file_path:
            return None
        legacy = self.pdf_file_path.lstrip("/")
        candidate = Path(settings.LEGACY_ROOT) / legacy
        return candidate if candidate.exists() else None


class PDFPage(models.Model):
    """One row per page of an indexed PDF. Powers full-text search."""

    document = models.ForeignKey(
        Document, related_name="pages", on_delete=models.CASCADE
    )
    page_number = models.PositiveIntegerField()
    text = models.TextField()

    class Meta:
        ordering = ["document_id", "page_number"]
        unique_together = ("document", "page_number")
        indexes = [
            models.Index(fields=["document", "page_number"]),
        ]

    def __str__(self):
        return f"{self.document} p.{self.page_number}"


class IFMAREvent(models.Model):
    year = models.PositiveIntegerField()
    class_name = models.CharField(max_length=100)
    results_data = models.TextField()

    class Meta:
        ordering = ["year", "class_name"]
        unique_together = ("year", "class_name")

    def __str__(self):
        return f"IFMAR {self.year} - {self.class_name}"


class Person(models.Model):
    ROLE_CHOICES = [("driver", "Driver"), ("industry", "Industry")]
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    role_type = models.CharField(max_length=20, choices=ROLE_CHOICES)
    bio_text = models.TextField(blank=True)

    class Meta:
        ordering = ["role_type", "name"]

    def __str__(self):
        return self.name


class Company(models.Model):
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PodcastEpisode(models.Model):
    title = models.CharField(max_length=250)
    date = models.DateField()
    audio_file = models.FileField(
        upload_to="podcast/",
        blank=True,
        help_text="Main audio file (optional if you add audio parts below).",
    )
    audio_link = models.CharField(
        max_length=500,
        blank=True,
        help_text="Optional external listen URL (used when no uploaded audio).",
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} - {self.title}"

    @property
    def audio_url(self):
        """First playback URL for backwards compatibility."""
        tracks = self.audio_tracks
        return tracks[0]["url"] if tracks else ""

    @property
    def audio_tracks(self):
        """All audio for this episode, in play order."""
        tracks = []
        if self.audio_file:
            tracks.append(
                {
                    "label": "",
                    "url": self.audio_file.url,
                    "hosted": True,
                }
            )
        for part in self.audio_parts.all():
            tracks.append(
                {
                    "label": part.label,
                    "url": part.audio_file.url,
                    "hosted": True,
                }
            )
        if not tracks and self.audio_link:
            tracks.append(
                {
                    "label": "",
                    "url": self.audio_link,
                    "hosted": False,
                }
            )
        return tracks

    def has_audio(self):
        return bool(self.audio_tracks)


class PodcastEpisodeAudio(models.Model):
    """Additional audio file for a multi-part episode."""

    episode = models.ForeignKey(
        PodcastEpisode,
        related_name="audio_parts",
        on_delete=models.CASCADE,
    )
    order = models.PositiveSmallIntegerField(default=0)
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text='Optional label, e.g. "Part 2".',
    )
    audio_file = models.FileField(upload_to="podcast/")

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.label or f"Part {self.pk}"

    @property
    def display_label(self):
        return self.label or "Part"


class ExternalLink(models.Model):
    title = models.CharField(max_length=150)
    url = models.URLField()
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title
