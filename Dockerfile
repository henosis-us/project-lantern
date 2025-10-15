# ──────────────────────────────────────────────────────────────
#  Lantern-Media-Server  - Dockerfile (with ffmpeg / ffprobe)
# ──────────────────────────────────────────────────────────────
FROM python:3.9-slim

# -------------------------------------------------------------
# 1. System-level packages (ffmpeg includes ffprobe)
# -------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------------------------------------
# 2. Python environment
# -------------------------------------------------------------
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# -------------------------------------------------------------
# 3. Application code
# -------------------------------------------------------------
COPY . .

# -------------------------------------------------------------
# 4. Entrypoint
# -------------------------------------------------------------
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]