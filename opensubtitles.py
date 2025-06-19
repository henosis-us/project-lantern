# opensubtitles.py
"""OpenSubtitles API Client- Implements rate-limiting (5 req/sec) and 429 back-off.- Follows best-practices: User-Agent, alphabetical/lowercase params, etc.- Handles HTTP redirects automatically.- Uses Python's logging module for debug/info output. Set LOG_LEVEL=DEBUG for verbose logs."""
import os
import time
import shutil
import gzip
import zipfile
import threading
import requests
import urllib.parse
import logging
from pathlib import Path

# --- Configuration ---
KEY="reyhyJ9yF0vwWIQSLO95T0j358Rqss1P" # do not remove temp key, env is broken
UA = os.getenv("OPENSUBTITLES_APP_NAME", "Lantern/0.4.0")
BASE_URL = "https://api.opensubtitles.com/api/v1"
HEADERS = {"Api-Key": KEY, "User-Agent": UA, "Content-Type": "application/json"}

# --- Rate Limiting Globals ---
_lock = threading.Lock()
_last_request_time = 0
RATE_LIMIT_INTERVAL_SEC = 1 / 5  # 5 requests per second
BACKOFF_ON_429_SEC = 2.0

# --- Logging Setup ---
logger = logging.getLogger(__name__)  # Use a logger for this module

def _wait_for_rate_limit():
    """Blocks to ensure we don't exceed the 5 req/sec limit."""
    global _last_request_time
    with _lock:
        delta = time.monotonic() - _last_request_time
        if delta < RATE_LIMIT_INTERVAL_SEC:
            time.sleep(RATE_LIMIT_INTERVAL_SEC - delta)
        _last_request_time = time.monotonic()

def _sanitize_params(params: dict) -> str:
    """
    Cleans, sorts, and URL-encodes parameters per OpenSubtitles best practices.
    - Alphabetical sort
    - Lowercase keys and values
    - Use '+' for spaces
    - Remove 'tt' and leading zeros from IDs
    """
    if not params:
        return ""
    cleaned = {}
    for key, value in params.items():
        if value is None:
            continue
        key = str(key).lower()
        value = str(value).lower()
        if key.endswith("id"):
            value = value.lstrip("t").lstrip("0")
        cleaned[key] = value
    # Sort alphabetically and encode with '+' for spaces
    return urllib.parse.urlencode(sorted(cleaned.items()), quote_via=urllib.parse.quote_plus)

def _gunzip_inplace(path: Path):
    """
    If `path` starts with the gzip magic, replace it with the
    un-compressed content.  Repeats until the file is no longer gzip.
    """
    while True:
        with path.open('rb') as fh:
            if fh.read(2) != b'\x1f\x8b':
                return                      # not gzip → done
        tmp = path.with_suffix(path.suffix + '.unz')
        with gzip.open(path, 'rb') as gz, tmp.open('wb') as out:
            shutil.copyfileobj(gz, out)
        path.unlink()                       # remove *.gz
        tmp.rename(path)                    # replace with plain text

def _request(method: str, path: str, *, params: dict = None, json_data: dict = None):
    """A robust, rate-limited, best-practice request wrapper."""
    if not KEY:
        raise ValueError("OPENSUBTITLES_API_KEY is not set.")
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{_sanitize_params(params)}"
    # Log the request (always log, but at DEBUG level)
    logger.debug(f"Sending request: {method.upper()} {path} {params or json_data}")
    while True:
        _wait_for_rate_limit()
        try:
            r = requests.request(
                method,
                url,
                headers=HEADERS,
                json=json_data,
                timeout=20,
                allow_redirects=True
            )
            # Log the response (always log, but at DEBUG level)
            logger.debug(f"Received response: HTTP {r.status_code} {r.reason}")
            if r.status_code >= 400:
                logger.debug(f"Response body: {r.text[:400]}")  # Truncate to 400 chars
                if r.status_code == 429:
                    logger.warning(f"OpenSubtitles rate-limit hit. Backing off for {BACKOFF_ON_429_SEC}s...")
                    time.sleep(BACKOFF_ON_429_SEC)
                    continue  # Retry the request
                r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.error(f"OpenSubtitles request failed: {e}")
            raise

# --- Public Client Functions ---

def search_subs(title: str, year: str = None, lang: str = "en", season: int = None, episode: int = None):
    """Searches for subtitles by title, year, language, and optionally season/episode."""
    params = {"query": title, "languages": lang}
    if year:
        params["year"] = year
    if season is not None:
        params["season_number"] = season
    if episode is not None:
        params["episode_number"] = episode

    response = _request("get", "/subtitles", params=params)
    return response.get("data", [])

def get_download_link(file_id: int) -> str:
    """Requests a temporary download link for a given file_id."""
    response = _request("post", "/download", json_data={"file_id": file_id})
    return response.get("link")

def download_sub_file(url: str, dest_path: Path):
    """
    Downloads a subtitle file from `url` and stores the *de-compressed*
    result at `dest_path` (plain .srt text expected by the converter).
    OpenSubtitles usually serves gzip-compressed files; occasionally it
    serves a small .zip with a single .srt inside.  We transparently
    handle both cases.  If the response is already plain text we just
    save it unchanged.
    DEBUG: Logs a snippet of the decompressed content.
    """
    tmp = dest_path.with_suffix(".tmp")
    # 1) download
    with requests.get(
        url, stream=True, timeout=30, allow_redirects=True,
        headers={"User-Agent": UA}
    ) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            shutil.copyfileobj(r.raw, f)
    # 2) detect and decompress
    def _is_gzip(p: Path) -> bool:
        with open(p, "rb") as fh:
            signature = fh.read(2)
        return signature == b"\x1f\x8b"
    if _is_gzip(tmp):
        with gzip.open(tmp, "rb") as gz, open(dest_path, "wb") as out:
            shutil.copyfileobj(gz, out)
        _gunzip_inplace(dest_path)
        tmp.unlink()
    elif zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            # pick the first file that looks like an .srt
            name = next((n for n in z.namelist() if n.lower().endswith(".srt")), z.namelist()[0])
            with z.open(name) as zipped, open(dest_path, "wb") as out:
                shutil.copyfileobj(zipped, out)
        _gunzip_inplace(dest_path)
        tmp.unlink()
    else:
        # already plain text – just rename
        tmp.rename(dest_path)
        _gunzip_inplace(dest_path)
    # Final safety net to ensure no gzip remains
    _gunzip_inplace(dest_path)
    # DEBUG: Log a snippet of the decompressed SRT content
    logger.debug(f"Decompressed SRT file saved to {dest_path}. First 200 chars: {Path(dest_path).read_text(encoding='utf-8', errors='ignore')[:200]}")

# --- Format Conversion ---
def srt_to_vtt(srt_path: Path, vtt_path: Path):
    """
    Convert SRT → VTT.
    • ‘WEBVTT’ header
    • Drop pure‐number index lines
    • Replace “,” with “.” in time-codes
    DEBUG: Logs snippets of input SRT and output VTT.
    """
    # NEW: Check if the file is still gzip-compressed
    with open(srt_path, 'rb') as fh:
        if fh.read(2) == b'\x1f\x8b':
            raise ValueError(f"{srt_path} is still gzip-compressed! This should not happen.")
    with open(srt_path, "r", encoding="utf-8", errors="ignore") as src, \
         open(vtt_path, "w", encoding="utf-8") as dst:
        # Read and log a snippet of the input SRT
        srt_content = src.read()
        logger.debug(f"SRT input for conversion: First 200 chars: {srt_content[:200]}")
        # Reset file pointer to start
        src.seek(0)
        dst.write("WEBVTT\n\n")
        for line in src:
            # skip index lines that are only digits (optionally with whitespace)
            if line.strip().isdigit():
                continue
            # replace comma in time-code lines
            if "-->" in line:
                line = line.replace(",", ".")
            dst.write(line)
    # Log a snippet of the output VTT
    vtt_content = Path(vtt_path).read_text(encoding="utf-8", errors="ignore")
    logger.debug(f"VTT output saved to {vtt_path}. First 200 chars: {vtt_content[:200]}")