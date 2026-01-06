# Project Lantern - Local Dev Setup (Windows)

This doc is the happy-path for a new developer to run the full stack locally:

- Identity Service (FastAPI + Postgres)
- Media Server (FastAPI + SQLite + FFmpeg)
- UI (Vite/React)

## Prereqs

Install these first:

- Git
- Python 3.11+ (and ensure `python` is on PATH)
- Node.js 18+
- PostgreSQL 15+ (local install)
- FFmpeg + FFprobe (must be on PATH)

Verify quickly:

```powershell
python --version
node --version
psql --version
ffmpeg -version
ffprobe -version
```

## 1) Clone

```powershell
git clone <YOUR_REPO_URL>
cd project-lantern
```

## 2) Postgres: create local user + DB

Open SQL Shell (psql) or pgAdmin and create a dev user + database:

```sql
CREATE USER lantern WITH PASSWORD 'lantern';
CREATE DATABASE lantern_identity OWNER lantern;
```

If you prefer using the default `postgres` superuser, that's fine too - just set `DATABASE_URL` accordingly.

## 3) Identity Service (port 8001)

```powershell
cd identity-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy env.example.txt .env
uvicorn main:app --reload --port 8001
```

Health check:

- http://localhost:8001/docs

## 4) Media Server (port 8000)

Open a new terminal:

```powershell
cd project-lantern
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy env.example.txt .env
uvicorn main:app --reload --port 8000
```

On startup you should see a printed Claim Token and the configured `LMS_PUBLIC_URL`.

Health check:

- http://localhost:8000/docs

## 5) UI (Vite dev server)

Open a new terminal:

```powershell
cd project-lantern\lantern-ui
npm install
copy env.local.example.txt .env.local
npm run dev
```

Open:

- http://localhost:5173

## 6) End-to-end checklist

1. Register a user in the UI
2. Login
3. Start the media server and copy its Claim Token
4. In UI - claim server using:
   - Server URL: `http://localhost:8000`
   - Claim Token: (from media server console)
5. Add a library path (point at a local folder with media)
6. Trigger a scan
7. Confirm movies/series appear
8. Start playback

## Common Issues

### FFmpeg not found

- Error will mention `FileNotFoundError` for `ffmpeg` or `ffprobe`.
- Fix: install FFmpeg and ensure it is on PATH, then restart the media server.

### CORS / Login issues

- Make sure:
  - Identity has `ALLOWED_ORIGINS=http://localhost:5173`
  - UI has `VITE_IDENTITY_BASE_URL=http://localhost:8001`

### Postgres auth failures

- Confirm the user/db exist and that `DATABASE_URL` matches your local install.
