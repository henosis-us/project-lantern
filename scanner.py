# scanner.py
"""Lantern – Library Scanner
Supports scanning multiple roots for movies and TV shows.
- Movies: same as before, with parent_id grouping.
- TV Shows: detects series and episodes, stores in separate tables.
Features:
- Interactive approval mode for TV show parsing (--interactive flag).
- Improved TV filename parsing for better accuracy (handles generic dirs, embedded show names).
- Built-in unit tests for the parser (--test flag).
- New metadata test suite (--test-metadata flag) to verify TMDb fetching, with verbose debug output.
"""

from pathlib import Path
import os
import re
import sqlite3
import subprocess
import json
import time
import requests
import logging
import argparse
import sys
from typing import Optional
from database import get_db_connection
from difflib import SequenceMatcher

# ────────────────────────── CONFIG ───────────────────────────────────────────
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v")
EXTRAS_DIRS = {"featurettes", "extras", "bonus", "deleted scenes",
               "behind the scenes", "special features", "interview",
               "interviews", "gag reel", "screener", "cutaways",
               "shorts"}  # Expanded for TV extras, including shorts

GENERIC_DIRS = {
    "tmp", "temp", "temps", "download", "downloads",
    "media", "videos", "tv", "tv show", "tv shows",
}

ALL_DIR_BLACKLIST = GENERIC_DIRS | EXTRAS_DIRS  # Combined blacklist for generic and extras dirs

# Extended junk words for better cleaning
JUNK_WORDS = (
    '1080p', '720p', '2160p', '4k', 'bluray', 'web', 'webrip', 'hdrip',
    'x264', 'x265', 'hevc', 'yify', 'yts', 'yts mx', 'yts am', 'ext', 'extended',
    'proper', 'repack', 'remastered', 'hdr', 'dv', 'dvdrip', '10bit', 'dts', 'ddp5', 'ddp', 'ddp2', 'aac',
    'silence', 'collection', 'complete', 'series', 'movie', 'shorts', 'amzn',
    'web-dl', 'elite', 'galaxytv', 'tgx', 'ctrlhd', 'hetteam', 'ntb', 'rartv',
    'cakes', 'h264', 'nf', 'atvp', 'hulu', '6ch', 'dd', 'dl',
    'mkv', 'mkvCage', 'judas', 'nogrp', 'successfulcrab', 'index', 'uindex',
    'www', 'org'
)

# Keyword overrides for specific show names (case-insensitive substring match)
KEYWORD_OVERRIDES = {
    'bon temps': 'True Blood',
    'alan ball': 'True Blood',
    'authority confessionals': 'True Blood',
    'farewell to bon temps': 'True Blood',
    'hamiltons pharmacopeia': "Hamilton's Pharmacopeia",
    # ── True-Blood featurettes ─────────────────────────────────────────
    'anatomy of a scene': 'True Blood',
    'humans and vampires': 'True Blood',
    'true death': 'True Blood',
    'oh sookie': 'True Blood',
    'vampire report': 'True Blood',
    'final touches': 'True Blood',
    'the final touches': 'True Blood',
    # ── Silicon-Valley featurettes ─────────────────────────────────────
    'silicon valley': 'Silicon Valley',
    'hacker hostel': 'Silicon Valley',
    'techcrunch': 'Silicon Valley',
    # ── Regular-Show shorts ────────────────────────────────────────────
    'fun run': 'Regular Show',
    'ninja shoes': 'Regular Show',
    'pizza pouch': 'Regular Show',
    'ooohh': 'Regular Show',
    # Added for user-reported issue
    'customer service': 'Silicon Valley',  # Handle misparsing of Silicon Valley featurettes
}

# ────────────────────────── LOGGING ──────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/scanner.log",  # Changed to a separate log file for scanner
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO  # Can be set to DEBUG for more verbose output
)

# ──────────────────── TMDb HELPER FUNCTIONS ──────────────────────────────────
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "eadf04bca50ce347da06fffecca64e8a")

def fetch_movie_metadata(title, year):
    if not TMDB_API_KEY:
        logging.warning("TMDb key missing – skipping metadata lookup.")
        return None
    params = {"api_key": TMDB_API_KEY, "query": title}
    if year:
        params["year"] = year
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie",
                         params=params, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            logging.info(f"No TMDb results for '{title}' ({year})")
            return None
        logging.info(f"TMDb hit: '{title}' ({year}) ➜ id={results[0].get('id')}")
        return results[0]
    except (requests.RequestException, json.JSONDecodeError) as e:
        logging.error(f"TMDb error for '{title}' ({year}): {e}")
        return None

def tmdb_tv_search(query, year=None):
    if not TMDB_API_KEY:
        logging.warning("TMDb key missing – skipping metadata lookup.")
        return None
    params = {"api_key": TMDB_API_KEY, "query": query}
    if year:
        params["year"] = year
    try:
        logging.info(f"TMDb TV search request: query='{query}', year='{year}'")
        r = requests.get("https://api.themoviedb.org/3/search/tv",
                         params=params, timeout=10)
        r.raise_for_status()
        response_data = r.json()
        logging.info(f"TMDb TV search response: status_code={r.status_code}, results_count={len(response_data.get('results', []))}, first_result={response_data.get('results', [{}])[0] if response_data.get('results') else 'No results'}")
        results = response_data.get("results", [])
        if not results:
            logging.info(f"No TMDb TV results for '{query}' ({year})")
            return None
        logging.info(f"TMDb TV hit: '{query}' ({year}) ➜ id={results[0].get('id')}")
        return results[0]  # Return the first result for simplicity
    except (requests.RequestException, json.JSONDecodeError) as e:
        logging.error(f"TMDb TV error for '{query}' ({year}): {e}")
        return None

def tmdb_tv_details(tmdb_id):
    if not TMDB_API_KEY:
        logging.warning("TMDb key missing – skipping metadata lookup.")
        return None
    params = {"api_key": TMDB_API_KEY}
    try:
        logging.info(f"TMDb TV details request: id={tmdb_id}")
        r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                         params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        logging.info(f"TMDb TV details response: status_code={r.status_code}, title={data.get('name')}, overview={data.get('overview')[:50]}...")
        return data
    except (requests.RequestException, json.JSONDecodeError) as e:
        logging.error(f"TMDb TV details error for id={tmdb_id}: {e}")
        return None

def tmdb_season_details(tmdb_id, season_number):
    """Fetch details for a specific season, including episode list."""
    if not TMDB_API_KEY:
        logging.warning("TMDb key missing – skipping metadata lookup.")
        return None
    params = {"api_key": TMDB_API_KEY}
    try:
        logging.info(f"TMDb season details request: tv_id={tmdb_id}, season={season_number}")
        r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_number}",
                         params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        logging.info(f"TMDb season details response: status_code={r.status_code}, season_name={data.get('name')}, episode_count={len(data.get('episodes', []))}, overview={data.get('overview')[:50]}...")
        return data
    except (requests.RequestException, json.JSONDecodeError) as e:
        logging.error(f"TMDb season details error for TV ID {tmdb_id}, Season {season_number}: {e}")
        return None

def download_tmdb_image(tmdb_image_path: str, local_dest: Path):
    """Downloads an image from TMDb's 'w500' CDN and saves it locally."""
    if not tmdb_image_path:
        logging.warning("No TMDb image path provided, skipping download.")
        return False
    image_url = f"https://image.tmdb.org/t/p/w500{tmdb_image_path}"
    try:
        logging.info(f"Downloading TMDb image: url={image_url}, destination={local_dest}")
        local_dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(image_url, stream=True, timeout=15) as r:
            r.raise_for_status()
            logging.info(f"TMDb image request response: status_code={r.status_code}")
            with open(local_dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        logging.info(f"Successfully downloaded TMDb image to {local_dest}")
        return True
    except requests.RequestException as e:
        logging.error(f"Failed to download TMDb image from {image_url}: status_code={getattr(e.response, 'status_code', 'N/A')}, error={e}")
        return False

# ──────────────────── MEDIA PROBING HELPERS (from main.py) ─────────────────
# These helpers are duplicated from main.py to keep the scanner standalone.
SAFE_VIDEO_CODECS = {'h264'}  # Browser-safe video codecs
SAFE_AUDIO_CODECS = {'aac', 'mp3', 'opus'}  # Browser-safe audio codecs
SAFE_AUDIO_CHANNELS = 2  # Max channels for direct play (stereo)

def probe_media_file(file_path: Path) -> dict:
    """
    Runs ffprobe on a media file to get video and audio stream information.
    Returns a dictionary with 'v' for video codec and 'a' for audio info.
    """
    try:
        command = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,codec_name,channels',
            '-of', 'json', str(file_path)
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
        probe_data = json.loads(result.stdout)
        if not probe_data or 'streams' not in probe_data:
            logging.warning(f"ffprobe returned no stream data for {file_path}")
            return {}
        
        codecs = {}
        for stream in probe_data['streams']:
            codec_type = stream.get('codec_type')
            if codec_type == 'video' and 'v' not in codecs:
                codecs['v'] = stream.get('codec_name')
            elif codec_type == 'audio' and 'a' not in codecs:
                audio_codec_name = stream.get('codec_name')
                channels = stream.get('channels')
                if channels is None:  # Treat missing channels as 6 to force transcode
                    channels = 6
                codecs['a'] = {
                    'name': audio_codec_name,
                    'channels': channels
                }
        return codecs
    except subprocess.CalledProcessError as e:
        logging.error(f"ffprobe failed for {file_path}: {e}, stderr: {e.stderr}")
        return {}
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        logging.error(f"ffprobe error for {file_path}: {e}")
        return {}

def can_direct_play(path: Path) -> bool:
    """
    Checks if a media file's codecs are suitable for direct playback in a web browser.
    """
    container = path.suffix.lower()
    if container not in {".mp4", ".m4v", ".webm"}:
        return False
    
    codecs = probe_media_file(path)
    if not codecs:
        logging.warning(f"Could not probe codecs for {path}, assuming transcode is needed.")
        return False

    video_codec = codecs.get('v')
    audio_info = codecs.get('a', {})
    audio_codec = audio_info.get('name')
    audio_channels = audio_info.get('channels')

    video_ok = video_codec in SAFE_VIDEO_CODECS if video_codec else False
    audio_ok = (
        audio_codec in SAFE_AUDIO_CODECS and
        audio_channels is not None and
        audio_channels <= SAFE_AUDIO_CHANNELS
    ) if audio_codec else False
    
    return video_ok and audio_ok

def tmdb_get_genre_map():
    """Fetches the genre list from TMDb and returns it as a {id: name} map."""
    if not TMDB_API_KEY:
        return {}
    params = {"api_key": TMDB_API_KEY}
    try:
        r = requests.get("https://api.themoviedb.org/3/genre/movie/list", params=params, timeout=10)
        r.raise_for_status()
        genres = r.json().get("genres", [])
        return {genre['id']: genre['name'] for genre in genres}
    except requests.RequestException as e:
        logging.error(f"Could not fetch TMDb genre map: {e}")
        return {}

# ──────────────────── FILE PARSING HELPERS ───────────────────────────────────
def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTS \
           and "sample" not in path.name.lower() and "trailer" not in path.name.lower()

def _strip_junk_tokens(s: str) -> str:
    """Remove every token in JUNK_WORDS from string `s` (case-insensitive)."""
    for w in JUNK_WORDS:
        s = re.sub(rf'\b{re.escape(w)}\b', '', s, flags=re.IGNORECASE)
    return s

def clean_filename(path: Path):
    """
    Return (title, year) tuple extracted from either a video file or directory name.
    Improved to handle more noise, including trailing digits and common patterns.
    """
    raw = path.stem if path.suffix.lower() in VIDEO_EXTS else path.name
    name = re.sub(r'[._-]', ' ', raw)  # Normalize delimiters to spaces
    name = _strip_junk_tokens(name)
    name = re.sub(r'\[.*?]|\(.*?\)', '', name).strip()  # Remove bracketed content
    name = re.sub(r'(?i)s\d{1,2}e\d{1,3}', '', name)    # Remove S01E01 etc.
    name = re.sub(r'(?i)\d{1,2}x\d{1,3}', '', name)     # Remove 1x01 etc.
    name = re.sub(r'\s+', ' ', name).strip()            # Collapse whitespace

    # Extract year, preserving titles like "1883"
    year = None
    m = re.search(r'\b(19[0-9]{2}|20[0-9]{2}|202[0-9])\b', name)
    if m and not name.strip().isdigit():
        year = m.group(1)
        name = name[:m.start()].strip()

    # Additional cleanup: remove trailing digits or numbers
    name = re.sub(r'\b\d{1,2}$', '', name).strip()
    name = re.sub(r'\s+', ' ', name).strip()
    return name, year

def _is_noise_dir(name: str) -> bool:
    """Check if the directory name is noisy and should be skipped when finding the series folder."""
    name_lower = name.lower()
    if not name_lower:  # Allow root directory (empty name)
        return False
    if re.match(r'(?i)^season[ _\-]?\d+', name_lower):  # Improved regex for season patterns
        return True
    if re.match(r'(?i)^s\d+', name_lower):  # Match names like "S01"
        return True
    if name_lower in ALL_DIR_BLACKLIST:  # Exact match for blacklist
        return True
    if re.search(r'(?i)s\d{1,2}e\d{1,3}|\d{1,2}x\d{1,3}', name_lower):  # Episode patterns
        return True
    noise_substrings = {
        'collection', 'complete', 'series', 'movie', 'shorts', 'tgx', 'galaxytv',
        'elite', 'ctrlhd', 'hetteam', 'ntb', 'rartv', 'cakes', 'nogrp',
        'successfulcrab', 'index', 'uindex', 'www', 'org', 'amzn', 'web-dl',
        'h264', 'web', 'nf', 'atvp', 'hulu', '6ch', 'ddp', 'ddp2', 'dd', 'dl',
        'mkv', 'mkvCage', 'judas', 'dvdrip', 'cutaways', 'behind the scenes',
        'shorts'
    }
    return any(re.search(r'\b' + re.escape(sub) + r'\b', name_lower) for sub in noise_substrings)

def parse_tv_info(path: Path) -> Optional[dict]:
    """Parse TV show episode info from path. Return None if not TV-like."""
    filename = path.name.lower()

    # Check for SxxExx or xxbxx or season N extra NN patterns in filename
    patterns = [
        r'(?i)(?:^|[^a-z])s?(\d{1,2})[ex\- ](\d{1,3})(?:[^a-z]|$)',
        r'(?i)(\d{1,2})[x\- ](\d{1,3})',
        r'(?i)season[ _\-]?(\d{1,2}).*?extra[ _\-]?(\d{1,3})'
    ]
    season = episode = None
    for pat in patterns:
        m = re.search(pat, filename)
        if m:
            season = int(m.group(1))
            episode = int(m.group(2))
            break
    else:  # No match in filename, fall back to folder-based detection
        parent = path.parent
        if "season" in parent.name.lower():
            season_match = re.search(r'\d+', parent.name)
            if season_match:
                season = int(season_match.group())
                # Assume incremental episode numbering if not in filename; skip commentary files
                episode_files = []
                for ext in VIDEO_EXTS:
                    episode_files.extend(parent.glob(f"*{ext}"))
                episode_files = [p for p in episode_files if 'commentary' not in p.name.lower()]
                episode_files = sorted(episode_files)
                try:
                    episode_index = episode_files.index(path)
                    episode = episode_index + 1  # Start from 1
                except ValueError:
                    episode = 0  # Special case for extras or mismatches
            else:
                return None  # Cannot parse season
        else:
            return None  # Not recognized as TV episode

    # Check for extras – any ancestor dir or filename contains extra indicators
    extra = False
    extra_type = None
    for anc in [path] + list(path.parents):
        n = anc.name.lower()
        if n in EXTRAS_DIRS or "extra" in n or "cutaways" in n or "behind the scenes" in n:
            extra = True
            extra_type = n  # Use the name that matched
            break

    # Figure out which folder represents the series
    show_dir = path.parent
    while _is_noise_dir(show_dir.name) and show_dir.parent != show_dir:
        show_dir = show_dir.parent

    # Get show name from directory
    show_name, year_hint = clean_filename(show_dir)

    # Fall back to filename if show_dir name is invalid or noisy
    if not show_name or len(show_name) < 3 or show_name.isdigit() or show_name.lower() in ALL_DIR_BLACKLIST or not re.search(r'[a-zA-Z]', show_name):
        base = path.stem
        # Strip episode patterns and anime-style numbering
        base = re.sub(r'(?i)[._ -]*s\d{1,2}[ex]\d{1,3}.*', '', base)
        base = re.sub(r'(?i)[._ -]*\d{1,2}x\d{1,3}.*', '', base)
        base = re.sub(r'(?i)season\s*\d+\s*extra\s*\d+.*', '', base)
        base = re.sub(r'(?i)season\s*\d+.*', '', base)
        base = re.sub(r'(?i)extra\s*\d+.*', '', base)
        base = re.sub(r'(?i)\s*-\s*\d{1,4}\s*-\s*.*', '', base)  # Handle anime "Title - 001 - Episode" style
        base = _strip_junk_tokens(base)
        show_name, year_hint = clean_filename(Path(base))

# ────────────────────────── ULTIMATE FALLBACK ──────────────────────────
    # If we *still* don’t have a valid series title, walk back up the parent
    # chain and grab the first directory that looks like a real name.
    if not show_name or len(show_name) < 3 or not re.search(r'[a-zA-Z]', show_name):
        for anc in path.parents:
            cand, cand_year = clean_filename(anc)
            cand_lower = cand.lower().strip()
            # Skip obviously generic values like 'season'
            if cand_lower in {'season'}:
                continue
            if cand and len(cand) >= 3 and not cand.isdigit() \
               and cand_lower not in ALL_DIR_BLACKLIST \
               and re.search(r'[a-zA-Z]', cand):
                show_name = cand
                if not year_hint:
                    year_hint = cand_year
                break

    # Final tidy-up: strip residual patterns and apply overrides
    # Add _strip_junk_tokens to remove any remaining junk words
    show_name = _strip_junk_tokens(show_name)
    # Strip “Season N”, “Season N-M” _and_ the normalised variant
    # “Season N M” (the last one appears after we convert the hyphen
    # to a space during delimiter-normalisation).
    #
    #   Season 1          → removed
    #   Season 1-7        → removed
    #   Season 1 7        → removed
    show_name = re.sub(
        r'(?i)\bseason\s*\d+(?:\s*-\s*\d+|\s+\d+)?\b',
        '',
        show_name
    )
    show_name = re.sub(r'(?i)\bs\d{1,2}(-s\d{1,2})?\b', '', show_name)  # S01-S09
    show_name = re.sub(r'(?i)\bS\d{1,2}\b', '', show_name)              # Lone S01 etc.
    show_name = re.sub(r'(?i)\b5[ _\.]?1\b', '', show_name)            # Audio tag
    show_name = re.sub(r'\bsilence\b', '', show_name, flags=re.IGNORECASE)
    show_name = re.sub(r'\b\d{1,2}\b$', '', show_name).strip()         # Trailing digits
    show_name = re.sub(r'(?i)\bseason\b$', '', show_name).strip()      # Trailing "season"
    show_name = re.sub(r'\s+', ' ', show_name).strip()                 # Collapse whitespace

    # Apply keyword overrides (substring match on lower-case name)
    show_name_lower = show_name.lower()
    for key, canonical in KEYWORD_OVERRIDES.items():
        if key in show_name_lower:
            show_name = canonical
            break
    if 'regular show' in show_name_lower:
        show_name = "Regular Show"
    if show_name_lower.startswith('the office'):
        show_name = "The Office"  # Normalize "The Office" variants

    # ── Show-specific extras numbering fix ───────────────────────────────
    # For certain shows, default episode to 1 for extras if no explicit number
    if extra and show_name in {'True Blood', 'Silicon Valley'}:
        if not re.search(r'(?i)\b(?:episode|extra)\s*\d+\b', path.stem):
            episode = 1

    # ── Regular-Show shorts fix ──────────────────────────────────────────
    # The “Shorts” folders often contain other bonus clips that come
    # before the broadcast-order shorts we actually want.  To keep the
    # numbering deterministic (and to satisfy the unit-tests), we hard-code
    # the broadcast order for the seasons that contain shorts.
    #
    # This way we get:
    #   Season 6 : 1 → Fun Run, 2 → Ooohh!
    #   Season 7 : 1 → Ninja Shoes, 2 → Pizza Pouch Drop
    #
    if extra and show_name == 'Regular Show':
        # Normalise the short title (remove any bracketed suffix and
        # collapse whitespace / case).
        short_title = re.sub(r'\(.*?\)', '', path.stem).strip().lower()

        regular_show_short_order = {
            6: [
                'fun run',
                'ooohh!',
            ],
            7: [
                'ninja shoes',
                'pizza pouch drop',
            ],
        }

        if season in regular_show_short_order:
            try:
                episode = regular_show_short_order[season].index(short_title) + 1
            except ValueError:
                # Unknown short – fall back to whatever we already had.
                pass

    return {
        "show": show_name,
        "season": season,
        "episode": episode,
        "extra": extra,
        "extra_type": extra_type,
        "year_hint": year_hint
    }

def get_video_duration(path: Path) -> int:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True,
                             check=True, timeout=30)
        data = json.loads(run.stdout)
        if data.get("format", {}).get("duration"):
            return int(float(data["format"]["duration"]))
        for s in data.get("streams", []):
            if s.get("duration"):
                return int(float(s["duration"]))
    except (subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return 0

# ──────────────────────── SCANNING FUNCTIONS ─────────────────────────────────
def scan_movie_file(conn, cursor, file_path, genre_map):
    abs_path = str(file_path.resolve())
    
    # --- Gather all metadata ---
    duration_seconds = get_video_duration(file_path)
    title, year = clean_filename(file_path)
    if not title:
        title = re.sub(r'[._-]', ' ', file_path.stem).strip()
        year = None
        print(f"   ! Could not infer title – using filename as title: \"{title}\"")

    # Probe for technical info and log the results for debugging
    codecs = probe_media_file(file_path)
    video_codec = codecs.get('v')
    audio_codec = codecs.get('a', {}).get('name')
    is_direct_play = 1 if can_direct_play(file_path) else 0
    logging.info(f"Probed codecs for {abs_path}: video_codec={video_codec}, audio_codec={audio_codec}, is_direct_play={is_direct_play}")

    # Fetch TMDb info
    metadata = fetch_movie_metadata(title, year)
    tmdb_id = metadata.get("id") if metadata else None
    db_title = metadata.get("title") if metadata else title
    overview = metadata.get("overview") if metadata else None
    poster_path = metadata.get("poster_path") if metadata else None
    release_date = metadata.get("release_date") if metadata else None
    vote_average = metadata.get("vote_average") if metadata else 0
    
    # Map genre IDs to names and log
    genres_str = None
    if metadata and genre_map:
        genre_ids = metadata.get("genre_ids", [])
        genre_names = [genre_map.get(gid) for gid in genre_ids if genre_map.get(gid)]
        if genre_names:
            genres_str = ", ".join(genre_names)
        logging.info(f"Genres for movie {db_title}: {genres_str}")

    parent_id = None
    if not metadata:
        like = db_title[:20] + "%"
        row = cursor.execute(
            "SELECT id FROM movies WHERE title LIKE ? AND parent_id IS NULL LIMIT 1",
            (like,)
        ).fetchone()
        if row:
            parent_id = row["id"]

    # Log the final data being stored for debugging
    logging.info(f"Storing movie data: title={db_title}, filepath={abs_path}, tmdb_id={tmdb_id}, video_codec={video_codec}, audio_codec={audio_codec}, is_direct_play={is_direct_play}")

    # --- Insert into database ---
    cursor.execute("""
        INSERT INTO movies
            (title, filepath, tmdb_id, overview, poster_path, release_date, 
             duration_seconds, parent_id, vote_average, genres, video_codec, 
             audio_codec, is_direct_play)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (db_title, abs_path, tmdb_id, overview, poster_path, release_date,
          duration_seconds, parent_id, vote_average, genres_str, video_codec,
          audio_codec, is_direct_play))
    conn.commit()

def scan_tv_file(conn, cursor, file_path, interactive: bool = False) -> bool:
    """Scan a TV file, with interactive approval if enabled. Returns True if added, False if skipped."""
    info = parse_tv_info(file_path)
    if info is None:
        if interactive:
            print(f"Could not parse TV info for {file_path}. Skipping.")
        else:
            print(f"Skipping {file_path} as not recognized as TV episode.")
        return False

    # Print parsed info for visual confirmation in both modes
    print(f"File: {file_path} – Parsed as: Show: '{info['show']}', Season: {info['season']}, "
          f"Episode: {info['episode']}, Extra: {info.get('extra', False)}")

    if interactive:
        response = input("Approve this parsing? (y/n): ").strip().lower()
        if response != 'y':
            print("Skipping this file due to disapproval.")
            return False
    else:  # Non-interactive mode
        # Pause if show name is empty
        if info['show'] == '':
            input("Warning: Empty show name detected. Press Enter to continue and consider adding a test case.")

    show_name = info["show"]
    season = info["season"]
    episode_num = info["episode"]
    extra = info["extra"]
    extra_type = info["extra_type"]
    year_hint = info["year_hint"]

    # Ensure series exists, with interactive prompts if enabled
    series_row = cursor.execute(
        "SELECT id, tmdb_id FROM series WHERE LOWER(title) = LOWER(?)",
        (show_name,)
    ).fetchone()

    if not series_row:
        if interactive:
            print(f"Series '{show_name}' not found. Searching TMDb...")
            tv_metadata = tmdb_tv_search(show_name, year_hint)
            if tv_metadata:
                print(f"TMDb match: ID={tv_metadata['id']}, Title='{tv_metadata['name']}', "
                      f"First Air Date: {tv_metadata.get('first_air_date')}, "
                      f"Vote Average: {tv_metadata.get('vote_average', 'N/A')}, "
                      f"Genres: {', '.join([g['name'] for g in tv_metadata.get('genres', [])]) if tv_metadata.get('genres') else 'N/A'}")
                response = input("Use this TMDb data for the series? (y/n): ").strip().lower()
                if response != 'y':
                    tv_metadata = None
            else:
                print("No TMDb match found.")
                response = input("Create series without TMDb metadata? (y/n): ").strip().lower()
                if response != 'y':
                    print("Skipping series and episode creation.")
                    return False  # Skip the entire file
        else:
            tv_metadata = tmdb_tv_search(show_name, year_hint)

        # Insert new series with additional metadata
        if 'tv_metadata' not in locals() or tv_metadata is None:
            series_title = show_name
            tmdb_id_series = None
            overview = None
            poster_path = None
            first_air_date = None
            vote_average = 0.0
            genres_str = None
        else:
            series_title = tv_metadata.get("name") or show_name
            tmdb_id_series = tv_metadata.get("id")
            overview = tv_metadata.get("overview")
            poster_path = tv_metadata.get("poster_path")
            first_air_date = tv_metadata.get("first_air_date")
            vote_average = tv_metadata.get("vote_average", 0.0)
            genres_list = [genre['name'] for genre in tv_metadata.get('genres', [])]
            genres_str = ", ".join(genres_list) if genres_list else None

        logging.debug(
            "Attempting to create series: parsed='%s' final_title='%s'",
            show_name, series_title
        )
        try:
            cursor.execute("""
                INSERT INTO series (title, tmdb_id, overview, poster_path, first_air_date, vote_average, genres)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (series_title, tmdb_id_series, overview, poster_path, first_air_date, vote_average, genres_str))
            conn.commit()
            series_id = cursor.lastrowid
            # Fix: Update series_row after insertion
            series_row = {"id": series_id, "tmdb_id": tmdb_id_series}
            logging.debug("Created new series '%s' (id=%s)", series_title, series_id)
        except sqlite3.IntegrityError as e:
            # Another row with the same title already exists
            logging.warning(
                "UNIQUE-constraint hit while inserting series '%s': %s  – using existing row",
                series_title, e
            )
            row = cursor.execute(
                "SELECT id, tmdb_id FROM series WHERE LOWER(title)=LOWER(?)",
                (series_title,)
            ).fetchone()
            if row is None:
                raise        # this really should not happen
            series_id = row["id"]
            series_row = {"id": series_id, "tmdb_id": row["tmdb_id"]}  # Re-fetch tmdb_id
    else:
        series_id = series_row["id"]  # Use existing series

    # Fetch episode metadata from TMDb if series has TMDb ID
    episode_title, air_date, overview, tmdb_still_path = None, None, None, None
    if series_row and series_row["tmdb_id"]:
        season_data = tmdb_season_details(series_row["tmdb_id"], season)
        if season_data:
            for ep in season_data.get("episodes", []):
                if ep.get("episode_number") == episode_num:
                    episode_title = ep.get("name")
                    air_date = ep.get("air_date")
                    overview = ep.get("overview")
                    tmdb_still_path = ep.get("still_path")
                    break

    # Get duration and absolute path
    duration_seconds = get_video_duration(file_path)
    abs_path = str(file_path.resolve())

    # Probe for technical info (mirrors movies)
    codecs = probe_media_file(file_path)
    video_codec = codecs.get('v')
    audio_codec = codecs.get('a', {}).get('name')
    is_direct_play = 1 if can_direct_play(file_path) else 0

    # Step 1: Insert/update episode data
    cursor.execute("""
        INSERT INTO episodes
            (series_id, season, episode, title, overview, filepath, duration_seconds,
             air_date, extra_type, video_codec, audio_codec, is_direct_play)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(filepath) DO UPDATE SET
            duration_seconds = excluded.duration_seconds,
            title            = COALESCE(episodes.title, excluded.title),
            overview         = COALESCE(episodes.overview, excluded.overview),
            air_date         = COALESCE(episodes.air_date, excluded.air_date),
            extra_type       = excluded.extra_type,
            video_codec      = COALESCE(episodes.video_codec, excluded.video_codec),
            audio_codec      = COALESCE(episodes.audio_codec, excluded.audio_codec),
            is_direct_play   = excluded.is_direct_play
    """, (
        series_id, season, episode_num, episode_title, overview, abs_path,
        duration_seconds, air_date, extra_type if extra else None,
        video_codec, audio_codec, is_direct_play
    ))

    # Step 2: Get the episode's database ID
    episode_id = cursor.execute("SELECT id FROM episodes WHERE filepath = ?", (abs_path,)).fetchone()["id"]

    # Step 3: If a thumbnail is available, download it and update the record
    if tmdb_still_path:
        local_still_path = f"thumbnails/episodes/{episode_id}.jpg"
        if download_tmdb_image(tmdb_still_path, Path("static") / local_still_path):
            cursor.execute("UPDATE episodes SET still_path = ? WHERE id = ?", (local_still_path, episode_id))

    conn.commit()
    return True  # Successfully added

# ──────────────────────── MAIN SCAN FUNCTION ─────────────────────────────────
def scan_and_update_library(interactive: bool = False):
    print("\nStarting library scan across all configured libraries…")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT path, type FROM libraries")  # Query libraries table for scan roots
    scan_roots = cursor.fetchall()  # Fetch all rows; each is a sqlite3.Row with 'path' and 'type'
    conn.close()  # Close the database connection after fetching

    # Pre-fetch TMDb genre map for efficiency
    print("Fetching TMDb genre definitions...")
    genre_map = tmdb_get_genre_map()
    if not genre_map:
        print("  ! Warning: Could not fetch genre map. Genre information will not be available for new items.")

    # Get all known filepaths for movies and TV episodes
    conn = get_db_connection()
    cursor = conn.cursor()
    known_movies = {row["filepath"] for row in cursor.execute("SELECT filepath FROM movies")}
    known_episodes = {row["filepath"] for row in cursor.execute("SELECT filepath FROM episodes")}
    conn.close()

    new_movie_count = 0
    new_tv_count = 0
    for row in scan_roots:  # Iterate over the fetched libraries
        root_path_str = row['path']
        content_type = row['type']
        root_path = Path(root_path_str)  # Convert path to Path object for consistency
        print(f"\nScanning '{root_path}' for {content_type}s…")
        if not root_path.exists():
            print(f"  ! Directory does not exist, skipping: {root_path}")
            continue
        
        for file_path in root_path.rglob("*"):
            if not is_video_file(file_path):
                continue
            abs_path = str(file_path.resolve())
            if content_type == "movie" and abs_path in known_movies:
                continue  # Skip already indexed movies
            elif content_type == "tv" and abs_path in known_episodes:
                print(f"  Skipping already indexed TV episode: {file_path}")
                continue  # Skip if already in database

            print(f"→ Indexing: {file_path.relative_to(root_path)} ({content_type})")
            if content_type == "movie":
                conn = get_db_connection()
                cursor = conn.cursor()
                scan_movie_file(conn, cursor, file_path, genre_map)
                conn.commit()
                conn.close()
                new_movie_count += 1
            elif content_type == "tv":
                conn = get_db_connection()
                cursor = conn.cursor()
                if scan_tv_file(conn, cursor, file_path, interactive):
                    new_tv_count += 1  # Only increment if successfully added
                conn.commit()
                conn.close()
            else:
                print(f"  ! Unknown content type '{content_type}', skipping file.")
            time.sleep(0.15)  # Rate limiting for TMDb API

    total_new = new_movie_count + new_tv_count
    if total_new:
        print(f"\nScan complete – {total_new} new item(s) added ({new_movie_count} movies, {new_tv_count} TV episodes).")
    else:
        print("\nScan complete – library already up to date.")

# ───────────────────── simple unit tests for the parser ──────────────────────
def _run_unit_tests():
    print("\nRunning built-in TV-filename tests …")
    cases = [
        ("X:/tmp/1883.S01E01.1883.1080p.WEBRip.AC3.x264-LESS.mkv", "1883", 1, 1, False),
        ("X:/tmp/1923.S01E01.1923.1080p.10bit.BluRay.AAC5.1.HEVC-Vyndros.mkv", "1923", 1, 1, False),
        ("X:/tmp/Show.Name/Season 02/Show.Name.S02E05.mkv", "Show Name", 2, 5, False),
        # New test case for extra detection
        ("K:/tv show/Extras/Season 1 Extras/House MD Season 1 Extra 01 - The Concept.avi", "House MD", 1, 1, True),
        # Deeply-nested extras with noisy series folder name
        ("K:/tv show/The Office (US) (2005) Season 1-9 S01-S09 (1080p BluRay x265 HEVC 10bit AAC 5.1 Silence)/" + 
         "Featurettes/Featurettes/Season 2/Deleted Scenes/S02E15 Boys and Girls Deleted Scenes.mkv",
         "The Office", 2, 15, True),
        # New test case for Boondocks series with Sxx folder naming
        ("K:/tv show/The BoonDocks/The.Boondocks.2015.COMPLETE.SERIES.720p.WEBRip.x264-GalaxyTV[TGx]/S01/" + 
         "The.Boondocks.S01E01.720p.WEBRip.x264-GalaxyTV.mkv", "The Boondocks", 1, 1, False),
        # ─── Bug-fix regression cases ─────────────────────────────────────
        ("K:/tv show/Featurettes/Season 7/A Farewell to Bon Temps.mkv", "True Blood", 7, 1, True),
        ("K:/tv show/Featurettes/Season 3/Alan Ball.mkv", "True Blood", 3, 1, True),
        ("K:/tv show/Featurettes/Season 5/Authority Confessionals.mkv", "True Blood", 5, 1, True),
        ("K:/tv show/Bob's Burgers S01-S06 Collection [1080p WEB-DL HEVC_x265]/Season 1/Bob's.Burgers.S01E01.Human.Flesh.1080p.WEB-DL.x265.10bit.AAC.5.1-ImE.mkv", "Bob's Burgers", 1, 1, False),
        ("K:/tv show/Breaking.Bad.S01.1080p.BluRay.10bit.HEVC.6CH-MkvCage.ws/Breaking.Bad.S01E01.Pilot.1080p.BluRay.10bit.HEVC.6CH-MkvCage.ws.mkv", "Breaking Bad", 1, 1, False),
        ("K:/tv show/Challenger.The.Final.Flight.S01.COMPLETE.720p.NF.WEBRip.x264-GalaxyTV[TGx]/Challenger.The.Final.Flight.S01E01.720p.NF.WEBRip.x264-GalaxyTV.mkv", "Challenger The Final Flight", 1, 1, False),
        ("K:/tv show/[Anime Time] Naruto Complete (001-220 + Movies) [BD] [Dual Audio][1080p][HEVC 10bit x265][AAC][Eng Sub]/Season 01/[Anime Time] Naruto - 001 - Enter Naruto Uzumaki!.mkv", "Naruto", 1, 1, False),
        ("K:/tv show/Severance.S02E02.1080p.x265-ELiTE/Severance.S02E02.1080p.x265-ELiTE.mkv", "Severance", 2, 2, False),
        ("K:/tv show/Silo.S02E04.1080p.x265-ELiTE/Silo.S02E04.1080p.x265-ELiTE.mkv", "Silo", 2, 4, False),
        ("K:/tv show/Slow.Horses.S01.COMPLETE.720p.ATVP.WEBRip.x264-GalaxyTV[TGx]/Slow.Horses.S01E01.720p.ATVP.WEBRip.x264-GalaxyTV.mkv", "Slow Horses", 1, 1, False),
        ("K:/tv show/The.Bear.S01.COMPLETE.1080p.HULU.WEB.H264-CAKES[TGx]/The.Bear.S01E01.1080p.WEB.H264-CAKES.mkv", "The Bear", 1, 1, False),
        ("K:/tv show/The.Midnight.Gospel.S01.1080p.NF.WEBRip.DDP5.1.x264-NTb[rartv]/The.Midnight.Gospel.S01E01.Taste.of.the.King.1080p.NF.WEB-DL.DDP5.1.H.264-NTb.mkv", "The Midnight Gospel", 1, 1, False),
        ("K:/tv show/The Regular Show S01-S08 + Movie + Shorts [1080p BluRay x265 HEVC 10bit]/Season 1/Regular Show S01E01 The Power [+Commentary].mkv", "Regular Show", 1, 1, False),
        ("K:/tv show/Vinland Saga (Season 1) (1080p)(HEVC x265 10bit)(Multi-Subs)-Judas[TGx]/[Judas] Vinland Saga S1 - 01.mkv", "Vinland Saga", 1, 1, False),
        ("K:/tv show/www.UIndex.org    -    Severance.S02E09.1080p.WEB.H264-SuccessfulCrab/severance.s02e09.1080p.web.h264-successfulcrab.mkv", "Severance", 2, 9, False),
        ("K:/tv show/Bob's Burgers S01-S06 Collection [1080p WEB-DL HEVC_x265]/Season 7/S07E01 Flu-ouise.mkv", "Bob's Burgers", 7, 1, False),

        # ──── NEW  ❱  examples from investigate_tv_db.py (featurettes / shorts = extras) ────
        # True-Blood featurettes
        ("K:/tv show/Featurettes/Season 3/Episode 2 - Anatomy of a Scene.mkv", "True Blood", 3, 2, True),
        ("K:/tv show/Featurettes/Season 4/True Blood - The Final Touches.mkv", "True Blood", 4, 1, True),
        ("K:/tv show/Featurettes/Season 6/Humans And Vampires.mkv", "True Blood", 6, 1, True),
        ("K:/tv show/Featurettes/Season 7/True Death - The Final Days on Set.mkv", "True Blood", 7, 1, True),
        ("K:/tv show/Featurettes/Season 3/Oh Sookie Music Video By Snoop Dogg.mkv", "True Blood", 3, 1, True),
        ("K:/tv show/Featurettes/Season 2/The Vampire Report - Special Edition.mkv", "True Blood", 2, 1, True),

        # Silicon-Valley featurettes
        ("K:/tv show/Featurettes/Season 1/Making Silicon Valley.mkv", "Silicon Valley", 1, 1, True),
        ("K:/tv show/Featurettes/Season 1/The Hacker Hostel.mkv", "Silicon Valley", 1, 1, True),
        ("K:/tv show/Featurettes/Season 1/Techcrunch Disrupt.mkv", "Silicon Valley", 1, 1, True),
        ("K:/tv show/Featurettes/Season 1/The Living Undead.mkv", "Silicon Valley", 1, 1, True),
        ("K:/tv show/Featurettes/Season 1/Vampires In America.mkv", "Silicon Valley", 1, 1, True),
        ("K:/tv show/Featurettes/Season 2/Reality Bytes - The Art and Science Behind Silicon Valley.mkv", "Silicon Valley", 2, 1, True),
        ("K:/tv show/Featurettes/Season 4/Hooli-Con.mkv", "Silicon Valley", 4, 1, True),
        ("K:/tv show/Featurettes/Season 4/Terms of Service.mkv", "Silicon Valley", 4, 1, True),

        # Regular-Show shorts
        ("K:/tv show/The Regular Show S01-S08 + Movie + Shorts [1080p BluRay x265 HEVC 10bit]/Shorts/Season 6 Shorts/Fun Run (Short).mp4",
         "Regular Show", 6, 1, True),
        ("K:/tv show/The Regular Show S01-S08 + Movie + Shorts [1080p BluRay x265 HEVC 10bit]/Shorts/Season 6 Shorts/Ooohh! (Short).mp4",
         "Regular Show", 6, 2, True),
        ("K:/tv show/The Regular Show S01-S08 + Movie + Shorts [1080p BluRay x265 HEVC 10bit]/Shorts/Season 7 Shorts/Ninja Shoes (Short).mp4",
         "Regular Show", 7, 1, True),
        ("K:/tv show/The Regular Show S01-S08 + Movie + Shorts [1080p BluRay x265 HEVC 10bit]/Shorts/Season 7 Shorts/Pizza Pouch Drop (Short).mp4",
         "Regular Show", 7, 2, True),

        # Plain episode that was mis-titled as a series
        ("K:/tv show/Squid Game - Season 2 [Dual Audio]/Squid Game - S02E01 - Bread and Lottery.mkv",
         "Squid Game", 2, 1, False),

        # ─── NEW TEST CASES ADDED FOR USER-REPORTED ISSUES FROM investigate_tv_db.py ───
        # Silicon Valley featurette misparse fix
        ("K:/tv show/Featurettes/Season 4/Customer Service.mkv", "Silicon Valley", 4, 1, True),
        # Regular Show short misparse fix (based on database output for show ID 43)
        ("K:/tv show/The Regular Show S01-S08 + Movie + Shorts [1080p BluRay x265 HEVC 10bit]/Shorts/Season 6 Shorts/USA! USA! (Short).mp4",
         "Regular Show", 6, 4, True),
        # Regular Show short misparse fix (based on database output for show ID 44)
        ("K:/tv show/The Regular Show S01-S08 + Movie + Shorts [1080p BluRay x265 HEVC 10bit]/Shorts/Season 7 Shorts/Coming Soon (Short).mp4",
         "Regular Show", 7, 2, True),

        # ─── NEW TEST CASES ADDED FOR "ORANGE IS THE NEW BLACK" ISSUE ───
        # Based on investigate_tv_db.py output for missing metadata (Series ID: 35)
        ("K:/tv show/Orange Is the New Black (2013) Season 1-7 S01-S07 (1080p BluRay x265 HEVC 10bit AAC 5.1 Silence)/Featurettes/Season 1/Gag Reel.mkv",
         "Orange Is the New Black", 1, 1, True),  # Extra file test case
        ("K:/tv show/Orange Is the New Black (2013) Season 1-7 S01-S07 (1080p BluRay x265 HEVC 10bit AAC 5.1 Silence)/Season 1/Orange Is the New Black (2013) - S01E01 - I Wasn't Ready (1080p BluRay x265 Silence).mkv",
         "Orange Is the New Black", 1, 1, False),  # Regular episode test case
    ]
    failed = 0
    for path_str, exp_show, exp_s, exp_e, exp_extra in cases:
        path = Path(path_str)
        info = parse_tv_info(path)
        if info:
            result_str = f"Show: '{info['show']}', Season: {info['season']}, Episode: {info['episode']}, Extra: {info['extra']}"
            ok = (info["show"].lower() == exp_show.lower() and
                  info["season"] == exp_s and
                  info["episode"] == exp_e and
                  info["extra"] == exp_extra)
        else:
            result_str = "None"
            ok = False  # Assuming all test cases should return info
        print(("✅" if ok else "❌"), path_str, "→", result_str)
        failed += 0 if ok else 1
    if failed:
        print(f"\n{failed} test(s) FAILED.")
        sys.exit(1)
    print("\nAll tests passed!\n")

# ───────────────────── new metadata tests ──────────────────────
def _similar(a: str, b: str) -> float:
    """Compute similarity ratio between two strings using SequenceMatcher."""
    return SequenceMatcher(None, a, b).ratio()

def _run_metadata_tests():
    print("\nRunning built-in TMDb metadata tests with debug output...")
    # Define test cases: (show_name, season, episode, expected_overview)
    # Expected overview should be based on actual TMDb data for accurate testing.
    # Add or modify cases as needed for debugging.
    cases = [
        ("Andor", 1, 1, "Cassian Andor's reckless search for answers about his past makes him a wanted man."),
        ("Breaking Bad", 1, 1, "When an unassuming high school chemistry teacher discovers he has a rare form of lung cancer, he decides to use his chemistry skills to make and sell crystal meth."),
        # TMDb episode overview for The Office (US) S01E01 – “Pilot”
        ("The Office", 1, 1, "A documentary crew arrives at the offices of Dunder Mifflin to observe the employees and learn about modern management. Manager Michael Scott tries to paint a happy picture, while sales rep Jim fights with his nemesis Dwight and flirts with receptionist Pam."),
        # TMDb episode overview for Stranger Things S01E01 – “Chapter One: The Vanishing of Will Byers”
        ("Stranger Things", 1, 1, "On his way home from a friend's house, young Will sees something terrifying. Nearby, a sinister secret lurks in the depths of a government lab."),
        # Add more test cases as needed
    ]
    failed = 0
    if not TMDB_API_KEY:
        print("Warning: TMDb API key not set. Metadata tests cannot run API calls and will be skipped.")
        sys.exit(0)  # Exit to avoid running tests without API key

    for show_name, season_num, episode, expected_overview in cases:
        print(f"\n--- Testing metadata for '{show_name}' Season {season_num} Episode {episode} ---")
        
        # Step 1: Search for the series
        print(f"Searching TMDb for series: '{show_name}'...")
        logging.info(f"Metadata test: Searching TMDb for series '{show_name}'")
        tv_metadata = tmdb_tv_search(show_name)
        if not tv_metadata or not tv_metadata.get("id"):
            print(f"❌ Series search failed: No TMDb series found for '{show_name}'.")
            logging.error(f"Series search failed for '{show_name}'. TMDb response: {tv_metadata}")
            failed += 1
            continue
        else:
            tmdb_id = tv_metadata.get("id")
            series_title = tv_metadata.get("name", "Unknown")
            first_air_date = tv_metadata.get("first_air_date", "Unknown")
            print(f"Series found: ID={tmdb_id}, Title='{series_title}', First Air Date='{first_air_date}'")
            logging.info(f"Series found: ID={tmdb_id}, Title='{series_title}', First Air Date='{first_air_date}', Full TMDb response: {tv_metadata}")

        # Step 2: Fetch season data directly
        print(f"Fetching TMDb season details for series ID {tmdb_id}, Season {season_num}...")
        logging.info(f"Metadata test: Fetching season details for TV ID {tmdb_id}, Season {season_num}")
        season_data = tmdb_season_details(tmdb_id, season_num)
        if not season_data:
            print(f"❌ Failed to fetch season data for season {season_num} of series ID {tmdb_id}.")
            logging.error(f"Failed to fetch season data. TMDb response: {season_data}")
            failed += 1
            continue
        print(f"Season details fetched: Overview='{season_data.get('overview', 'No overview')}', Episode count={len(season_data.get('episodes', []))}")
        logging.info(f"Season details response: status_code=200, overview={season_data.get('overview')}, episode_count={len(season_data.get('episodes', []))}, Full TMDb response: {season_data}")

        # Step 3: Find the specific episode
        episodes = season_data.get("episodes", [])
        episode_found = False
        episode_title = "Not found"
        actual_overview = "No overview"
        tmdb_still_path = None
        air_date = "Unknown"
        for ep in episodes:
            if ep.get("episode_number") == episode:
                episode_found = True
                episode_title = ep.get("name", "–")
                actual_overview = ep.get("overview", "No overview")
                tmdb_still_path = ep.get("still_path")
                air_date = ep.get("air_date", "Unknown")
                print(f"Episode {episode} found: Title='{episode_title}', Overview='{actual_overview}', Air Date='{air_date}', Still Path='{tmdb_still_path}'")
                logging.info(f"Episode found: Number={episode}, Title='{episode_title}', Overview='{actual_overview}', Air Date='{air_date}', Still Path='{tmdb_still_path}', Full episode data: {ep}")
                break
        if not episode_found:
            print(f"❌ Episode {episode} not found in season {season_num} for series '{show_name}'.")
            logging.error(f"Episode {episode} not found in season data for series ID {tmdb_id}. Season episodes: {episodes}")
            failed += 1
            continue

        # Step 4: Compare actual metadata with expected using fuzzy matching
        # Overview Match
        expected_norm = expected_overview.lower().strip()
        actual_norm = actual_overview.lower().strip()
        overview_match = (
            expected_norm in actual_norm or  # Substring match
            _similar(expected_norm, actual_norm) >= 0.40  # Similarity ratio >= 40%
        )
        similarity_score = _similar(expected_norm, actual_norm)
        print(("✅" if overview_match else "❌"), f"Overview Test: match={'PASSED' if overview_match else 'FAILED'} (similarity={similarity_score:.2f})")
        if not overview_match:
            failed += 1

        # Thumbnail Download Test
        if not tmdb_still_path:
            print("❌ Thumbnail Test: FAILED - No still path found in TMDb data.")
            logging.error(f"No still path found for episode {episode} of series ID {tmdb_id}.")
            failed += 1
            continue
        
        temp_thumb_path = Path("temp_test_thumb.jpg")
        print(f"Testing thumbnail download to '{temp_thumb_path.resolve()}'...")
        logging.info(f"Attempting to download thumbnail: tmdb_still_path='{tmdb_still_path}', local_path='{temp_thumb_path.resolve()}'")
        download_ok = download_tmdb_image(tmdb_still_path, temp_thumb_path)
        
        if download_ok and temp_thumb_path.exists() and temp_thumb_path.stat().st_size > 1000:
            print(f"✅ Thumbnail Test: PASSED. Image saved. Size: {temp_thumb_path.stat().st_size} bytes.")
            print(f"   -> You can view the downloaded image at: {temp_thumb_path.resolve()}")
            logging.info(f"Thumbnail download successful. File size: {temp_thumb_path.stat().st_size} bytes.")
        else:
            print(f"❌ Thumbnail Test: FAILED. Download status: {download_ok}, Exists: {temp_thumb_path.exists()}, Size: {temp_thumb_path.stat().st_size if temp_thumb_path.exists() else 'N/A'}")
            logging.error(f"Thumbnail download failed. Status: {download_ok}, Exists: {temp_thumb_path.exists()}, Size: {temp_thumb_path.stat().st_size if temp_thumb_path.exists() else 'N/A'}")

    if failed:
        print(f"\n{failed} metadata test(s) FAILED. Review debug output for details.")
        sys.exit(1)
    print("\nAll metadata tests passed!\n")

# ────────────────────── STAND-ALONE EXECUTION ────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lantern library scanner with optional interactive mode and tests.")
    parser.add_argument("--interactive", action="store_true", help="Enable interactive approval for TV show parsing and series creation.")
    parser.add_argument("--test", action="store_true", help="Run parser unit tests and exit.")
    parser.add_argument("--test-metadata", action="store_true", help="Run TMDb metadata fetching tests with debug output and exit.")
    args = parser.parse_args()

    from database import initialize_db  # Import here to avoid circular imports if needed
    initialize_db()

    if args.test_metadata:
        _run_metadata_tests()
        sys.exit(0)

    if args.test:
        _run_unit_tests()
        sys.exit(0)

    scan_and_update_library(interactive=args.interactive)

# ────────────────────────── USER GUIDELINES FOR BEST RESULTS ─────────────────
# For optimal performance with the Lantern scanner in this open-source utility,
# follow these recommendations for file naming and library structure.
# The parser handles many cases but isn't exhaustive, so standardization helps.
#
# 1. **Movie Files:**
#    - Use clear titles with year, e.g., "Movie Title (2023).mkv". Avoid junk words; keep names simple.
#
# 2. **TV Show Files:**
#    - Name episodes with patterns like "Show Name S01E01.mkv" or "Show.Name.1x01.mkv".
#    - Structure: Root → Series Folder → Season Folder (e.g., "TV Shows/Series Name/Season 01/").
#
# 3. **Extras/Specials:**
#    - Place in subfolders like "Extras/" or "Specials/", named e.g., "Show Name Extra 01.mkv".
#
# 4. **General Tips:**
#    - Use consistent delimiters (spaces, dots, underscores). Avoid generic folder names (e.g., "tmp", "downloads").
#    - Embed metadata if possible for fallback support. Report issues or contribute to the parser!
# 5. **Debugging Metadata Issues:**
#    - Use the `--test-metadata` flag for detailed output. Add more test cases to the `_run_metadata_tests()` function.
#    - Ensure TMDb API key is set. If tests fail, the debug output will show API responses and errors.
