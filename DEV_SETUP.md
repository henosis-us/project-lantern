# Project Lantern — Local Development Setup (Windows)

This document is the **happy-path** setup for running the full Lantern stack locally on Windows:

- **Identity Service** (FastAPI + PostgreSQL)
- **Media Server** (FastAPI + SQLite + FFmpeg)
- **Lantern UI** (Vite/React)

If anything in this guide breaks for a fresh clone, update the validation notes in:

- `dev_lantern/VALIDATION_LOG.md`

---

## Ports / URLs (defaults)

- Identity Service: `http://localhost:8001`
- Media Server: `http://localhost:8000`
- UI dev server: `http://localhost:5173`

---

## Prerequisites

Install these first:

- Git
- Python **3.11+** (ensure `python` is on PATH)
- Node.js **18+** (ensure **`npm`** is on PATH)
- PostgreSQL **15+** (local install)
- FFmpeg + FFprobe (on PATH)

Verify your toolchain:

```powershell
python --version
node --version
npm --version
psql --version
ffmpeg -version
ffprobe -version
```

---

## 1) Clone

```powershell
git clone https://github.com/henosis-us/project-lantern.git
cd project-lantern
```

---

## 2) PostgreSQL (local): create dev user + database

1) Install PostgreSQL (15+) using the official Windows installer.

2) Ensure `psql` is available (either add the Postgres `bin` folder to PATH, or use the SQL Shell shortcut).

3) Create a dev user + database.

Open **SQL Shell (psql)** (or use pgAdmin) and run:

```sql
CREATE USER lantern WITH PASSWORD 'lantern';
CREATE DATABASE lantern_identity OWNER lantern;
```

Notes:

- Using `postgres` superuser is fine too; just set `DATABASE_URL` accordingly.
- Default local Postgres port is `5432`.

---

## 3) Identity Service (FastAPI + Postgres)

### 3.1 Create venv + install deps

```powershell
cd identity-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 Configure environment

Copy the example environment file:

```powershell
copy env.example.txt .env
```

Then confirm `identity-service/.env` contains a valid Postgres connection string, e.g.:

```env
DATABASE_URL=postgresql://lantern:lantern@localhost:5432/lantern_identity
JWT_SECRET_KEY=dev-only-change-me
IDENTITY_PUBLIC_URL=http://localhost:8001
ALLOWED_ORIGINS=http://localhost:5173
```

### 3.3 Run

```powershell
uvicorn main:app --reload --port 8001
```

Health check:

- `http://localhost:8001/docs`

---

## 4) Media Server (FastAPI + SQLite + FFmpeg)

Open a **new** terminal.

### 4.1 Create venv + install deps

```powershell
cd project-lantern
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4.2 Configure environment

```powershell
copy env.example.txt .env
```

Recommended dev defaults in `project-lantern/.env`:

```env
LMS_PUBLIC_URL=http://localhost:8000
IDENTITY_SERVICE_URL=http://localhost:8001
DATABASE_PATH=data/lantern.db
ALLOWED_ORIGINS=http://localhost:5173
```

### 4.3 Run

```powershell
uvicorn main:app --reload --port 8000
```

On startup, the media server will print a **Claim Token**.

Health check:

- `http://localhost:8000/docs`

---

## 5) Lantern UI (Vite dev server)

Open a **new** terminal.

```powershell
cd project-lantern\lantern-ui
npm install
copy env.local.example.txt .env.local
npm run dev
```

Open:

- `http://localhost:5173`

---

## 6) End-to-end checklist (manual)

1) Open the UI: `http://localhost:5173`
2) Register a user
3) Login
4) Start the media server and copy its Claim Token
5) In the UI, claim the server using:
   - Server URL: `http://localhost:8000`
   - Claim Token: (from the media server console)
6) Add a library path (point at a local folder with media)
7) Trigger a scan
8) Confirm movies/series appear
9) Start playback

---

## 7) Optional: quick backend smoke test

This repo includes a small in-process smoke test that validates:

- Identity service can boot against Postgres
- Media server can boot and fetch a claim token

From `project-lantern/`:

```powershell
python workspace\lantern_integration_smoketest.py
```

It uses `DATABASE_URL` if you set it, or you can override explicitly:

```powershell
python workspace\lantern_integration_smoketest.py --database-url postgresql://lantern:lantern@localhost:5432/lantern_identity
```

---

## Troubleshooting

### `npm` not found

- Symptom: `npm : The term 'npm' is not recognized...`
- Fix: reinstall Node.js (18+ LTS recommended) and ensure **Add to PATH** is enabled.

### `psql` not found

- Symptom: `psql : The term 'psql' is not recognized...`
- Fix: add the Postgres `bin` folder to PATH or use the SQL Shell shortcut.

### Postgres connection errors

- Verify Postgres is running and listening on `localhost:5432`.
- Confirm your `DATABASE_URL` points at the correct user/db.
- If auth fails, re-check the user/password you created.

### FFmpeg not found

- Symptom: errors mention `FileNotFoundError` for `ffmpeg` or `ffprobe`.
- Fix: install FFmpeg and ensure both `ffmpeg` and `ffprobe` are on PATH, then restart the media server.

### CORS / login issues

- Identity must allow the UI origin:
  - `identity-service/.env`: `ALLOWED_ORIGINS=http://localhost:5173`
- UI must point at local identity:
  - `lantern-ui/.env.local`: `VITE_IDENTITY_BASE_URL=http://localhost:8001`
