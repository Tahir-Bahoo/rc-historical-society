from django.apps import AppConfig


class ArchiveConfig(AppConfig):
    name = "archive"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401
