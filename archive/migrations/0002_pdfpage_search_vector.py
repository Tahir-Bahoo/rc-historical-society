"""Add Postgres full-text search column for PDF pages (no-op on SQLite)."""

from django.db import migrations


def add_search_vector(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        ALTER TABLE archive_pdfpage
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED;
        """
    )
    schema_editor.execute(
        """
        CREATE INDEX IF NOT EXISTS archive_pdfpage_search_vector_idx
        ON archive_pdfpage USING GIN (search_vector);
        """
    )


def remove_search_vector(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS archive_pdfpage_search_vector_idx;")
    schema_editor.execute("ALTER TABLE archive_pdfpage DROP COLUMN IF EXISTS search_vector;")


class Migration(migrations.Migration):

    dependencies = [
        ("archive", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_search_vector, remove_search_vector),
    ]
