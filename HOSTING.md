# RC Historical Society — Hosting Guide

This document is for whoever deploys and maintains the site on a server. It covers server requirements, first-time setup, day-to-day operations, and troubleshooting.

---

## What you are hosting

The site is a **Django** web app with a separate **FastAPI search service**. Both share one **PostgreSQL** database. **Nginx** sits in front and serves static files, uploaded media, and proxies requests to Django.

| Service   | Role                                      | Port (internal) |
|-----------|-------------------------------------------|-----------------|
| nginx     | Public web server                         | 80              |
| django    | Website + admin panel                     | 8000            |
| search    | Full-text PDF search API                  | 8001            |
| db        | PostgreSQL database                       | 5432            |

**Stack:** Python 3.12, Django 6, FastAPI, PostgreSQL 16, Nginx, Docker Compose.

---

## Server requirements

- **OS:** Linux (Ubuntu 22.04+ recommended)
- **RAM:** 2 GB minimum, 4 GB recommended (PDF indexing uses memory)
- **Disk:** Depends on archive size; plan for PDFs + database + Docker images. Start with **20 GB+** free.
- **Software:** Docker Engine and Docker Compose plugin
- **Domain:** Point DNS `A` record(s) to the server IP (e.g. `rchistoricalsociety.org`, `www.rchistoricalsociety.org`)

---

## First-time setup

### 1. Clone the repository

```bash
git clone <repository-url> rc-historical-society
cd rc-historical-society
```

### 2. Create environment file

```bash
cp .env.example .env
nano .env   # or use your preferred editor
```

**Required changes in `.env`:**

| Variable | What to set |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Long random string (50+ characters). Generate with: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `0` in production |
| `DJANGO_ALLOWED_HOSTS` | Your domain(s), comma-separated, e.g. `rchistoricalsociety.org,www.rchistoricalsociety.org` |
| `POSTGRES_PASSWORD` | Strong database password |
| `CORS_ORIGINS` | Your public site URL with `https://`, e.g. `https://rchistoricalsociety.org` |

Leave `POSTGRES_HOST=db` and `SEARCH_SERVICE_URL=http://search:8001` as shown in `.env.example` when using Docker Compose.

### 3. Build and start containers

```bash
docker compose up -d --build
```

Wait until all four services are running:

```bash
docker compose ps
```

All services should show `running` (db should be `healthy`).

### 4. Run database migrations

**Do this on every deploy** when the codebase includes new migrations:

```bash
docker compose exec django python manage.py migrate
```

### 5. Create an admin user

Site content is managed at `/admin/`. Create the first login:

```bash
docker compose exec django python manage.py createsuperuser
```

Follow the prompts for username, email, and password.

### 6. (Optional) Import legacy PDFs

If the old site’s PDF folders are on the server, the project can register them without re-uploading:

```bash
docker compose exec django python manage.py seed_legacy_pdfs
```

Then index them for search:

```bash
docker compose exec django python manage.py reindex_pdfs
```

Large archives may take a while. You can run with `--only-missing` to skip already-indexed files:

```bash
docker compose exec django python manage.py reindex_pdfs --only-missing
```

### 7. Enable HTTPS (strongly recommended)

Docker Compose exposes **port 80 only**. For production you should add TLS. Common options:

**Option A — Caddy or Certbot in front of Docker**  
Terminate HTTPS on the host and reverse-proxy to `localhost:80`.

**Option B — Cloudflare**  
Put the domain behind Cloudflare proxy (orange cloud). Set `DJANGO_SSL_REDIRECT=1` in `.env` (default when `DEBUG=0`).

**Option C — Extend nginx in the repo**  
Add Let’s Encrypt / SSL config to `deploy/nginx.conf` and expose port 443 in `docker-compose.yml`.

After HTTPS is working, confirm the site loads at `https://your-domain.org` and admin login works.

---

## What the admin needs to know

### Uploading PDFs

- Log in at `https://your-domain.org/admin/`
- Go to **Documents** → Add or edit a document → upload the PDF
- **Large files (up to ~400 MB)** are supported
- After save, search indexing runs **in the background** (may take 30–60 seconds for big scans)
- Refresh the document page to confirm **page count** and **indexed at** are filled in
- If search does not work, select the document(s) in the list and use action **“Reindex selected PDFs”**

### Other content

All site content is editable in Django admin:

- Homepage posts, people, companies, podcast episodes, IFMAR results, external links, etc.

No code changes are needed for routine content updates.

---

## Day-to-day operations

### View logs

```bash
docker compose logs -f              # all services
docker compose logs -f django       # website only
docker compose logs -f search       # search service only
```

### Restart after config changes

```bash
docker compose up -d --build
```

### Restart one service

```bash
docker compose restart django
```

### Backups (important)

Back up regularly:

1. **PostgreSQL database**
   ```bash
   docker compose exec db pg_dump -U rchs rchs > backup-$(date +%F).sql
   ```
   (Use your actual `POSTGRES_USER` and `POSTGRES_DB` from `.env`.)

2. **Uploaded files** — Docker volume `mediadata` holds PDFs and podcast audio:
   ```bash
   docker volume inspect rc-historical-society_mediadata
   ```
   Back up that volume path or copy from the running container:
   ```bash
   docker compose exec django tar -czf /tmp/media-backup.tar.gz -C /app/django_project media
   docker compose cp django:/tmp/media-backup.tar.gz ./media-backup.tar.gz
   ```

### Deploying updates

When new code is pushed:

```bash
git pull
docker compose up -d --build
docker compose exec django python manage.py migrate
docker compose exec django python manage.py collectstatic --noinput
```

(`collectstatic` also runs during the Docker build; running it again after deploy is safe if static files changed.)

---

## Upload size limits

Magazine PDFs can be large. Limits are configured in three places — keep them aligned:

| Layer | Setting | Default |
|-------|---------|---------|
| Nginx | `client_max_body_size` in `deploy/nginx.conf` | 400 MB |
| Django | `DATA_UPLOAD_MAX_MB` in `.env` | 400 MB |
| Django | `FILE_UPLOAD_MAX_MB` in `.env` | 10 MB (larger files stream to disk) |

To allow bigger uploads, increase **both** Nginx and `DATA_UPLOAD_MAX_MB`, then rebuild:

```bash
docker compose up -d --build
```

---

## Troubleshooting

### Site returns 502 / Bad Gateway

- Check Django is running: `docker compose logs django`
- Restart: `docker compose restart django`

### Search returns “service unavailable”

- Check search container: `docker compose logs search`
- Confirm `SEARCH_SERVICE_URL=http://search:8001` in `.env`
- Restart search: `docker compose restart search`

### Admin PDF upload fails (413 or timeout)

- Confirm `client_max_body_size 400M;` is in `deploy/nginx.conf` (or `/etc/nginx/sites-available/django.conf` on EC2)
- Confirm `DATA_UPLOAD_MAX_MB=400` in `.env`
- Rebuild: `docker compose up -d --build`
- Check disk space: `df -h`

### “No such table” errors

Migrations were not applied:

```bash
docker compose exec django python manage.py migrate
```

### PDF saved but not searchable

Reindex manually:

```bash
docker compose exec django python manage.py reindex_pdfs --only-missing
```

Or in admin: select documents → **Reindex selected PDFs**.

### Static files or CSS missing

```bash
docker compose exec django python manage.py collectstatic --noinput
docker compose restart nginx
```

---

## Local development (optional)

For testing on a laptop without Docker:

```bash
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
cp .env.example .env   # leave POSTGRES_* blank to use SQLite
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

In a second terminal, start search:

```bash
uvicorn search_service.main:app --reload --port 8001
```

---

## Support checklist for go-live

- [ ] `.env` filled in with real secret key, domain, and DB password
- [ ] `docker compose up -d --build` succeeds
- [ ] `migrate` completed
- [ ] Superuser created
- [ ] HTTPS working
- [ ] Homepage loads
- [ ] Admin login works
- [ ] Test PDF upload in admin (large file if possible)
- [ ] Search returns results after indexing
- [ ] Database and media backup plan in place

---

## Contact

For application questions or content issues, contact the RC Historical Society project owner. For server/infrastructure issues, refer to this guide and the logs from `docker compose logs`.
