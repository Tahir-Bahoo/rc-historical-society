import logging

import httpx
from django.conf import settings
from django.shortcuts import render
from django.views.generic import DetailView, ListView, TemplateView

from .models import Company, Document, ExternalLink, HomepagePost, IFMAREvent, Person, PodcastEpisode

logger = logging.getLogger(__name__)


class HomeView(ListView):
    template_name = "archive/home.html"
    model = HomepagePost
    context_object_name = "posts"


class MagazineIndexView(TemplateView):
    template_name = "archive/magazine_scans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["magazines"] = [
            ("Competition Plus - The R/C Magazine", "competition_plus"),
            ("Rev-Up - The Official Magazine of ROAR", "rev_up"),
            ("Radio Control Model Cars", "rc_model_cars"),
            ("Xtreme RC Cars", "xtreme_rc_cars"),
        ]
        return context


class MagazineGridView(TemplateView):
    template_name = "archive/magazine_grid.html"
    category = ""
    title = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        docs = Document.objects.filter(category=self.category).order_by("year", "month")
        month_rows = {}
        for doc in docs:
            month_rows.setdefault(doc.year, []).append(doc)
        context["title"] = self.title
        context["month_rows"] = sorted(month_rows.items())
        return context


class CompetitionPlusView(MagazineGridView):
    category = "competition_plus"
    title = "Competition Plus"


class RevUpView(MagazineGridView):
    category = "rev_up"
    title = "Rev-Up"


class RCModelCarsView(MagazineGridView):
    category = "rc_model_cars"
    title = "R/C Model Cars"


class XtremeRCCarsView(MagazineGridView):
    category = "xtreme_rc_cars"
    title = "Xtreme RC Cars"


class SimpleDocumentListView(TemplateView):
    template_name = "archive/document_list.html"
    category = ""
    title = ""
    grouped = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        docs = Document.objects.filter(category=self.category).order_by("brand", "publication_name")
        context["title"] = self.title
        context["grouped"] = self.grouped
        grouped_docs = {}
        if self.grouped:
            for doc in docs:
                grouped_docs.setdefault(doc.brand or "Other", []).append(doc)
            context["grouped_docs"] = grouped_docs.items()
        else:
            context["documents"] = docs
        return context


class RaceProgramsView(SimpleDocumentListView):
    title = "Race Programs and Rules"
    category = "race_programs_rules"


class CatalogsView(SimpleDocumentListView):
    title = "Catalogs"
    category = "catalogs"
    grouped = True


class ManualsView(SimpleDocumentListView):
    title = "Manuals / Documents"
    category = "manuals"
    grouped = True


class IFMARView(TemplateView):
    template_name = "archive/ifmar_main.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["years"] = list(range(1985, 2026, 2))
        context["available_years"] = set(IFMAREvent.objects.values_list("year", flat=True).distinct())
        return context


class IFMARYearView(TemplateView):
    template_name = "archive/ifmar_year.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = kwargs["year"]
        context["year"] = year
        context["events"] = IFMAREvent.objects.filter(year=year)
        return context


class PeopleView(TemplateView):
    template_name = "archive/people.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["drivers"] = Person.objects.filter(role_type="driver")
        context["industry_leaders"] = Person.objects.filter(role_type="industry")
        return context


class PersonDetailView(DetailView):
    template_name = "archive/person_detail.html"
    model = Person
    slug_field = "slug"
    slug_url_kwarg = "slug"


class CompanyView(ListView):
    template_name = "archive/companies.html"
    model = Company
    context_object_name = "companies"


class PodcastView(ListView):
    template_name = "archive/podcast.html"
    model = PodcastEpisode
    context_object_name = "episodes"


class LinksView(ListView):
    template_name = "archive/links.html"
    model = ExternalLink
    context_object_name = "links"


class AcknowledgementsView(TemplateView):
    template_name = "archive/acknowledgements.html"


class SearchView(TemplateView):
    """Render PDF full-text search results by calling the FastAPI service."""

    template_name = "archive/search_results.html"
    page_size = 20

    def _build_page_range(self, current: int, total_pages: int, edge: int = 2, around: int = 2):
        """Compact pagination range, e.g. 1 ... 4 5 [6] 7 8 ... 25.

        Returns a list of ints (page numbers) and ``None`` entries (gaps)."""
        if total_pages <= 1:
            return [1] if total_pages == 1 else []

        keep = set(range(1, edge + 1))
        keep.update(range(total_pages - edge + 1, total_pages + 1))
        keep.update(range(max(1, current - around), min(total_pages, current + around) + 1))
        keep = sorted(p for p in keep if 1 <= p <= total_pages)

        result, prev = [], 0
        for page in keep:
            if prev and page - prev > 1:
                result.append(None)
            result.append(page)
            prev = page
        return result

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        category = (self.request.GET.get("category") or "").strip()
        try:
            page = max(1, int(self.request.GET.get("page", 1)))
        except (TypeError, ValueError):
            page = 1

        context.update(
            query=query,
            category=category,
            categories=Document.CATEGORY_CHOICES,
            results=[],
            total=0,
            error=None,
            page=page,
            page_size=self.page_size,
            total_pages=0,
            page_range=[],
            has_prev=False,
            has_next=False,
            prev_page=page - 1,
            next_page=page + 1,
            start_index=0,
            end_index=0,
            querystring="",
        )

        if not query:
            return context

        if len(query) < 2:
            context["error"] = "Please enter at least 2 characters to search."
            return context

        offset = (page - 1) * self.page_size
        params = {"q": query, "limit": self.page_size, "offset": offset}
        if category:
            params["category"] = category

        try:
            response = httpx.get(
                f"{settings.SEARCH_SERVICE_URL.rstrip('/')}/api/search",
                params=params,
                timeout=settings.SEARCH_SERVICE_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            context["results"] = payload.get("results", [])
            context["total"] = payload.get("total", 0)
        except httpx.HTTPError as exc:
            logger.warning("Search service error: %s", exc)
            context["error"] = (
                "The search service is currently unavailable. Please try again shortly."
            )
            return context

        total = context["total"]
        total_pages = (total + self.page_size - 1) // self.page_size if total else 0
        if total_pages and page > total_pages:
            context["page"] = page = total_pages

        # Build the querystring (without `page=`) that pagination links append to
        extras = []
        if query:
            extras.append(("q", query))
        if category:
            extras.append(("category", category))
        querystring = "&".join(f"{k}={v}" for k, v in extras)

        context.update(
            total_pages=total_pages,
            page_range=self._build_page_range(page, total_pages),
            has_prev=page > 1,
            has_next=page < total_pages,
            prev_page=page - 1,
            next_page=page + 1,
            start_index=offset + 1 if context["results"] else 0,
            end_index=offset + len(context["results"]),
            querystring=querystring,
        )
        return context
