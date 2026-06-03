from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("archive", "0003_podcastepisode_audio_file_alter_audio_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="PodcastEpisodeAudio",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("order", models.PositiveSmallIntegerField(default=0)),
                (
                    "label",
                    models.CharField(
                        blank=True,
                        help_text='Optional label, e.g. "Part 2".',
                        max_length=120,
                    ),
                ),
                ("audio_file", models.FileField(upload_to="podcast/")),
                (
                    "episode",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_parts",
                        to="archive.podcastepisode",
                    ),
                ),
            ],
            options={
                "ordering": ["order", "id"],
            },
        ),
        migrations.AlterField(
            model_name="podcastepisode",
            name="audio_file",
            field=models.FileField(
                blank=True,
                help_text="Main audio file (optional if you add audio parts below).",
                upload_to="podcast/",
            ),
        ),
        migrations.AlterField(
            model_name="podcastepisode",
            name="audio_link",
            field=models.CharField(
                blank=True,
                help_text="Optional external listen URL (used when no uploaded audio).",
                max_length=500,
            ),
        ),
    ]
