# ALS Dashboard — Heroku deployment

This folder is a self-contained GitHub repository for deploying the ALS Dashboard
as one Heroku web dyno.

## Architecture

- FastAPI serves both the API and the static vanilla HTML/CSS/JavaScript frontend.
- Python parses uploaded `.xlsx` workbooks and converts Infix checks to YAML.
- SQLite stores the currently loaded study in `/tmp/als_dashboard.sqlite3`.
- The SQLite file is intentionally ephemeral. A dyno restart, redeploy, or replacement
  clears the uploaded study, after which a user must upload the workbook again.
- Run exactly one web dyno. Separate or additional dynos do not share their files and
  can show different current studies.

The uploaded workbook is not stored in the browser DOM. Its bytes are read by the
backend, parsed, and discarded; the normalized study is kept in the temporary SQLite
database. All visitors to the same running dyno share that current study.

## Files that belong in GitHub

- `backend/` — API, workbook parser, temporary SQLite access, and YAML conversion
- `frontend/` — dashboard HTML, CSS, and JavaScript
- `requirements.txt` — production Python dependencies
- `Procfile` — Heroku web process and temporary database location
- `.python-version` — Heroku Python runtime selection
- `.gitignore` — excludes workbooks, databases, environments, and caches
- `README.md` — deployment and operating notes

Do not commit real ALS workbooks, generated SQLite databases, `.env` files, virtual
environments, or Python cache files. ALS workbooks can contain sensitive study
metadata; use Heroku access controls appropriate to the data.

## Deploy from a new GitHub repository

From this directory:

```powershell
git init
git add .
git commit -m "Prepare ALS Dashboard for Heroku"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

Then either connect the repository in the Heroku Dashboard and deploy `main`, or use
the Heroku CLI:

```powershell
heroku login
heroku create YOUR_HEROKU_APP_NAME
heroku git:remote -a YOUR_HEROKU_APP_NAME
git push heroku main
heroku ps:scale web=1
heroku open
```

Heroku detects the Python app from `requirements.txt`. The `Procfile` starts Uvicorn
on Heroku's assigned `$PORT` and pins the service to one worker so every request in
the dyno uses the same temporary SQLite database.

## Local smoke test

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:ALS_DASHBOARD_DB = Join-Path $env:TEMP "als_dashboard_heroku_test.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The status endpoint is `GET /api/status`.

## Persistence limitation

This package intentionally has no managed database. If the current study must survive
restarts, if multiple dynos must serve the same study, or if multiple users need
isolated studies, migrate persistence to a shared managed database (typically Heroku
Postgres) and add authentication/tenant isolation before production use.
