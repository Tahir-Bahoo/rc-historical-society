from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("archive", "0002_document_indexed_at_document_page_count_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="podcastepisode",
            name="audio_file",
            field=models.FileField(
                blank=True,
                help_text="Upload an MP3 or other audio file to host on this site.",
                upload_to="podcast/",
            ),
        ),
        migrations.AlterField(
            model_name="podcastepisode",
            name="audio_link",
            field=models.CharField(
                blank=True,
                help_text="Optional external listen URL (used when no file is uploaded).",
                max_length=500,
            ),
        ),
    ]
