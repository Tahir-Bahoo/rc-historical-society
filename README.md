# RC Historical Society

Archive website for radio control racing history — magazine scans, catalogs, manuals, IFMAR results, podcast, and full-text PDF search.

**Live site:** [rchistoricalsociety.org](https://rchistoricalsociety.org)

## For developers

```bash
python3 -m venv env && source env/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
# second terminal:
uvicorn search_service.main:app --reload --port 8001
```

## For hosting / deployment

See **[HOSTING.md](HOSTING.md)** — full server setup, Docker, HTTPS, backups, admin PDF uploads, and troubleshooting.
