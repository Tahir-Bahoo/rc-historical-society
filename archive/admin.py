from django.contrib import admin, messages
from django.utils.html import format_html

from .indexing import queue_document_for_index
from .models import (
    Company,
    Document,
    ExternalLink,
    HomepagePost,
    IFMAREvent,
    PDFPage,
    Person,
    PodcastEpisode,
    PodcastEpisodeAudio,
)


admin.site.site_header = "RC Historical Society — Admin"
admin.site.site_title = "RCHS Admin"
admin.site.index_title = "Content management"


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "publication_name",
        "category",
        "year",
        "month",
        "brand",
        "available",
        "page_count",
        "indexed_at",
        "pdf_preview",
    )
    list_filter = ("category", "available", "year", "brand")
    search_fields = ("publication_name", "brand", "pdf_file_path")
    list_editable = ("available",)
    actions = ("reindex_selected",)
    readonly_fields = ("indexed_at", "page_count")
    fieldsets = (
        ("Identity", {"fields": ("publication_name", "category", "brand")}),
        ("Issue details", {"fields": ("year", "month", "available")}),
        (
            "PDF source",
            {
                "fields": ("pdf_file", "pdf_file_path"),
                "description": (
                    "Upload a PDF (preferred) or set a legacy path. "
                    "Search indexing is queued for a background worker "
                    "(does not run inside the web process — avoids crashes on large files)."
                ),
            },
        ),
        ("Index status", {"fields": ("page_count", "indexed_at")}),
    )

    @admin.display(description="PDF")
    def pdf_preview(self, obj):
        url = obj.pdf_url
        if not url:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Open</a>', url)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not (obj.pdf_file or obj.pdf_file_path):
            return

        messages.info(
            request,
            f"PDF saved for '{obj.publication_name}'. "
            "Search indexing is queued for the background worker "
            "(page_count / indexed_at update when that finishes). "
            "The site stays online while indexing runs.",
        )

    @admin.action(description="Queue selected PDFs for search reindex")
    def reindex_selected(self, request, queryset):
        queued = 0
        for doc in queryset:
            if doc.pdf_file or doc.pdf_file_path:
                queue_document_for_index(doc)
                queued += 1
        self.message_user(
            request,
            f"Queued {queued} document(s) for the background index worker. "
            "Ensure process_index_queue is running under Supervisor.",
        )


@admin.register(PDFPage)
class PDFPageAdmin(admin.ModelAdmin):
    list_display = ("document", "page_number", "snippet")
    list_filter = ("document__category",)
    search_fields = ("text", "document__publication_name")
    readonly_fields = ("document", "page_number", "text")

    @admin.display(description="Snippet")
    def snippet(self, obj):
        return (obj.text[:140] + "…") if len(obj.text) > 140 else obj.text


@admin.register(HomepagePost)
class HomepagePostAdmin(admin.ModelAdmin):
    list_display = ("date", "title", "linked_page")
    list_filter = ("date",)
    search_fields = ("title", "description")
    date_hierarchy = "date"
    fieldsets = (
        ("Post", {"fields": ("date", "title", "description")}),
        ("Media & link", {"fields": ("image", "linked_page")}),
    )


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("name", "role_type", "slug")
    list_filter = ("role_type",)
    search_fields = ("name", "bio_text")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name", "description")


class PodcastEpisodeAudioInline(admin.TabularInline):
    model = PodcastEpisodeAudio
    extra = 1
    fields = ("order", "label", "audio_file")
    ordering = ("order", "id")


@admin.register(PodcastEpisode)
class PodcastEpisodeAdmin(admin.ModelAdmin):
    list_display = ("date", "title", "audio_source", "audio_preview")
    list_filter = ("date",)
    search_fields = ("title", "description")
    date_hierarchy = "date"
    inlines = (PodcastEpisodeAudioInline,)
    fieldsets = (
        ("Episode", {"fields": ("date", "title", "description")}),
        (
            "Audio",
            {
                "fields": ("audio_file", "audio_link"),
                "description": (
                    "Upload the main audio file, add more files in the Audio parts "
                    "section below for multi-part episodes, or paste an external listen URL."
                ),
            },
        ),
    )

    @admin.display(description="Source")
    def audio_source(self, obj):
        count = len(obj.audio_tracks)
        if count > 1:
            return f"{count} files"
        if obj.audio_file or obj.audio_parts.exists():
            return "Uploaded"
        if obj.audio_link:
            return "External link"
        return "—"

    @admin.display(description="Audio")
    def audio_preview(self, obj):
        url = obj.audio_url
        if not url:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Listen</a>', url)


@admin.register(IFMAREvent)
class IFMAREventAdmin(admin.ModelAdmin):
    list_display = ("year", "class_name")
    list_filter = ("year", "class_name")
    search_fields = ("class_name", "results_data")


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ("title", "url")
    search_fields = ("title", "description", "url")
