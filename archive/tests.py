from django.test import TestCase

from archive.models import Document, PodcastEpisode, PodcastEpisodeAudio
from archive.views import _build_magazine_year_grids, _magazine_issue_label


class MagazineYearGridTests(TestCase):
    def test_builds_four_by_three_month_table(self):
        for month in ("January", "April", "July", "October"):
            Document.objects.create(
                publication_name=f"Issue {month}",
                category="rc_model_cars",
                year=1990,
                month=month,
                available=True,
                pdf_file_path=f"rc_model_cars/{month.lower()}.pdf",
            )

        grids = _build_magazine_year_grids(
            Document.objects.filter(category="rc_model_cars", year=1990)
        )
        self.assertEqual(len(grids), 1)
        grid = grids[0]
        self.assertEqual(grid["year"], 1990)
        self.assertEqual(len(grid["rows"]), 4)
        self.assertEqual(len(grid["rows"][0]), 3)
        self.assertEqual(grid["rows"][0][0]["month"], "January")
        self.assertEqual(grid["rows"][0][0]["label"], "January 1990")
        self.assertIsNotNone(grid["rows"][0][0]["doc"])
        self.assertIsNone(grid["rows"][0][1]["doc"])

    def test_issue_label_formats_combined_months(self):
        doc = Document(
            publication_name="Winter",
            category="competition_plus",
            year=1987,
            month="Dec/Jan",
        )
        self.assertEqual(_magazine_issue_label(doc, 1987), "Dec / Jan 1987")

    def test_combined_months_slot_into_grid(self):
        doc = Document.objects.create(
            publication_name="Winter Issue",
            category="competition_plus",
            year=1987,
            month="Dec/Jan",
            available=True,
            pdf_file_path="competition-plus/winter.pdf",
        )
        grids = _build_magazine_year_grids(Document.objects.filter(pk=doc.pk))
        january = grids[0]["rows"][0][0]
        self.assertEqual(january["doc"], doc)
        self.assertEqual(january["label"], "Dec / Jan 1987")
        self.assertEqual(grids[0]["extras"], [])

    def test_unrecognized_months_go_to_extras(self):
        doc = Document.objects.create(
            publication_name="Special Issue",
            category="competition_plus",
            year=1986,
            month="Annual",
            available=True,
            pdf_file_path="competition-plus/special.pdf",
        )
        grids = _build_magazine_year_grids(Document.objects.filter(pk=doc.pk))
        self.assertEqual(len(grids[0]["extras"]), 1)
        self.assertEqual(grids[0]["extras"][0]["doc"], doc)
        self.assertEqual(grids[0]["extras"][0]["label"], "Annual 1986")


class PodcastEpisodeTests(TestCase):
    def test_audio_url_prefers_uploaded_file(self):
        episode = PodcastEpisode(
            title="Test",
            date="2020-01-01",
            audio_link="https://example.com/external.mp3",
        )
        episode.audio_file.name = "podcast/test.mp3"
        self.assertTrue(episode.audio_url.endswith("podcast/test.mp3"))

    def test_audio_url_falls_back_to_external_link(self):
        episode = PodcastEpisode(
            title="Test",
            date="2020-01-01",
            audio_link="https://example.com/episode.mp3",
        )
        self.assertEqual(episode.audio_url, "https://example.com/episode.mp3")

    def test_audio_tracks_includes_main_and_parts(self):
        episode = PodcastEpisode.objects.create(
            title="Test",
            date="2020-01-01",
            audio_link="https://example.com/main.mp3",
        )
        episode.audio_file.name = "podcast/main.mp3"
        episode.save()
        PodcastEpisodeAudio.objects.create(
            episode=episode,
            order=1,
            label="Part 2",
            audio_file="podcast/part2.mp3",
        )
        episode = PodcastEpisode.objects.prefetch_related("audio_parts").get(pk=episode.pk)
        self.assertEqual(len(episode.audio_tracks), 2)
        self.assertEqual(episode.audio_tracks[1]["label"], "Part 2")
