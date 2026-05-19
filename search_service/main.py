"""FastAPI full-text search over indexed PDF pages.

Reads directly from the same database Django writes to (SQLite in dev,
Postgres in prod). Auto-detects the dialect and switches between simple
``LIKE`` matching (SQLite) and Postgres ``ts_headline`` / ``tsvector`` for
ranked, highlighted snippets.

Run with::

    uvicorn search_service.main:app --reload --port 8001
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

HERE = Path(__file__).resolve().parent


def _find_sqlite() -> Path | None:
    """Locate the Django ``db.sqlite3`` regardless of where this package sits.

    Walks up from this file and checks a few obvious sibling/child locations.
    Returns ``None`` if nothing is found, in which case we still build a sane
    default path that mirrors the conventional layout.
    """
    for parent in [HERE, *HERE.parents]:
        candidates = [
            parent / "db.sqlite3",
            parent / "django_project" / "db.sqlite3",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
    return None


def _default_sqlite_url() -> str:
    found = _find_sqlite()
    if found is not None:
        return f"sqlite:///{found}"
    fallback = HERE.parent / "django_project" / "db.sqlite3"
    return f"sqlite:///{fallback}"


def _database_url() -> str:
    """Compose a SQLAlchemy URL from env, defaulting to the Django SQLite."""
    if url := os.environ.get("SEARCH_DATABASE_URL"):
        return url
    if pg_db := os.environ.get("POSTGRES_DB"):
        user = os.environ.get("POSTGRES_USER", "postgres")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        auth = f"{user}:{password}" if password else user
        return f"postgresql+psycopg://{auth}@{host}:{port}/{pg_db}"
    return _default_sqlite_url()


_DB_URL = _database_url()
# SQLite caches a single connection by default which means writes from other
# processes (e.g. Django admin uploads) are not visible until reconnect. Force
# NullPool for SQLite so every query opens a fresh connection and always sees
# the latest committed state. Postgres keeps the regular pooled behaviour.
if _DB_URL.startswith("sqlite"):
    ENGINE: Engine = create_engine(_DB_URL, future=True, poolclass=NullPool)
else:
    ENGINE = create_engine(_DB_URL, future=True, pool_pre_ping=True)
IS_POSTGRES = ENGINE.dialect.name == "postgresql"

MEDIA_URL = os.environ.get("MEDIA_URL", "/media/")
STATIC_URL = os.environ.get("STATIC_URL", "/static/")


def _build_pdf_url(pdf_file: Optional[str], pdf_file_path: Optional[str]) -> str:
    if pdf_file:
        return f"{MEDIA_URL.rstrip('/')}/{pdf_file.lstrip('/')}"
    if pdf_file_path:
        return f"{STATIC_URL.rstrip('/')}/{pdf_file_path.lstrip('/')}"
    return ""


class SearchHit(BaseModel):
    document_id: int
    document_name: str
    category: str
    year: Optional[int] = None
    month: Optional[str] = None
    page_number: int
    snippet: str
    pdf_url: str


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchHit]


app = FastAPI(
    title="RC Historical Society Search",
    version="1.0.0",
    description="Full-text PDF search across the magazine, catalog, and manual archive.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


SNIPPET_WINDOW = 90


def _make_snippet(text_blob: str, query: str) -> str:
    """Plain-text snippet builder for SQLite. Highlights with <mark> tags."""
    if not text_blob:
        return ""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    match = pattern.search(text_blob)
    if not match:
        return text_blob[:200].replace("\n", " ").strip() + "…"
    start = max(match.start() - SNIPPET_WINDOW, 0)
    end = min(match.end() + SNIPPET_WINDOW, len(text_blob))
    chunk = text_blob[start:end].replace("\n", " ").strip()
    highlighted = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", chunk)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text_blob) else ""
    return f"{prefix}{highlighted}{suffix}"


def _search_postgres(q: str, category: Optional[str], limit: int, offset: int) -> tuple[int, list[SearchHit]]:
    where = ["p.search_vector @@ websearch_to_tsquery('english', :q)"]
    params: dict = {"q": q, "limit": limit, "offset": offset}
    if category:
        where.append("d.category = :category")
        params["category"] = category

    where_sql = " AND ".join(where)
    count_sql = f"""
        SELECT COUNT(*)
        FROM archive_pdfpage p
        JOIN archive_document d ON d.id = p.document_id
        WHERE {where_sql}
    """
    rows_sql = f"""
        SELECT
            d.id AS document_id,
            d.publication_name,
            d.category,
            d.year,
            d.month,
            d.pdf_file,
            d.pdf_file_path,
            p.page_number,
            ts_headline(
                'english', p.text,
                websearch_to_tsquery('english', :q),
                'StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MinWords=8, MaxWords=24'
            ) AS snippet,
            ts_rank(p.search_vector, websearch_to_tsquery('english', :q)) AS rank
        FROM archive_pdfpage p
        JOIN archive_document d ON d.id = p.document_id
        WHERE {where_sql}
        ORDER BY rank DESC, d.year DESC NULLS LAST, p.page_number ASC
        LIMIT :limit OFFSET :offset
    """
    with ENGINE.connect() as conn:
        total = conn.execute(text(count_sql), params).scalar_one()
        rows = conn.execute(text(rows_sql), params).mappings().all()

    hits = [
        SearchHit(
            document_id=r["document_id"],
            document_name=r["publication_name"],
            category=r["category"],
            year=r["year"],
            month=r["month"],
            page_number=r["page_number"],
            snippet=r["snippet"] or "",
            pdf_url=_build_pdf_url(r["pdf_file"], r["pdf_file_path"]),
        )
        for r in rows
    ]
    return total, hits


def _search_sqlite(q: str, category: Optional[str], limit: int, offset: int) -> tuple[int, list[SearchHit]]:
    like = f"%{q}%"
    where = ["p.text LIKE :like_q"]
    params: dict = {"like_q": like, "limit": limit, "offset": offset, "q": q}
    if category:
        where.append("d.category = :category")
        params["category"] = category
    where_sql = " AND ".join(where)

    count_sql = f"""
        SELECT COUNT(*)
        FROM archive_pdfpage p
        JOIN archive_document d ON d.id = p.document_id
        WHERE {where_sql}
    """
    rows_sql = f"""
        SELECT
            d.id AS document_id,
            d.publication_name,
            d.category,
            d.year,
            d.month,
            d.pdf_file,
            d.pdf_file_path,
            p.page_number,
            p.text
        FROM archive_pdfpage p
        JOIN archive_document d ON d.id = p.document_id
        WHERE {where_sql}
        ORDER BY d.year DESC, p.page_number ASC
        LIMIT :limit OFFSET :offset
    """
    with ENGINE.connect() as conn:
        total = conn.execute(text(count_sql), params).scalar_one()
        rows = conn.execute(text(rows_sql), params).mappings().all()

    hits = [
        SearchHit(
            document_id=r["document_id"],
            document_name=r["publication_name"],
            category=r["category"],
            year=r["year"],
            month=r["month"],
            page_number=r["page_number"],
            snippet=_make_snippet(r["text"], q),
            pdf_url=_build_pdf_url(r["pdf_file"], r["pdf_file_path"]),
        )
        for r in rows
    ]
    return total, hits


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "dialect": ENGINE.dialect.name}


@app.get("/api/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=2, description="Search query"),
    category: Optional[str] = Query(None, description="Restrict to a Document category"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SearchResponse:
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query is empty")

    if IS_POSTGRES:
        total, hits = _search_postgres(q, category, limit, offset)
    else:
        total, hits = _search_sqlite(q, category, limit, offset)

    return SearchResponse(query=q, total=total, results=hits)
