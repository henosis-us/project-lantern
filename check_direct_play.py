# check_direct_play.py
from pathlib import Path
import os
import sys
import re
import collections

# --- Configuration from scanner.py ---
# Define multiple scan roots with types, mimicking scanner.py
# IMPORTANT: Adjust these paths to match your actual setup.
SCAN_ROOTS = [
    {"path": Path(r"K:\Movies"), "type": "movie"},
    {"path": Path(r"K:\tv show"), "type": "tv"},
    # Add more roots as needed, e.g., {"path": Path(r"Z:\AnotherDir"), "type": "movie"}
]

VIDEO_EXTS       = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v")
EXTRAS_DIRS      = {"featurettes", "extras", "bonus", "deleted scenes",
                    "behind the scenes", "special features", "interview",
                    "interviews", "gag reel", "screener", "cutaways",
                    "shorts"} # Added from scanner for consistency

GENERIC_DIRS = {
    "tmp", "temp", "temps", "download", "downloads",
    "media", "videos", "tv", "tv show", "tv shows",
}
ALL_DIR_BLACKLIST = GENERIC_DIRS | EXTRAS_DIRS

JUNK_WORDS = (
    '1080p', '720p', '2160p', '4k', 'bluray', 'web', 'webrip', 'hdrip',
    'x264', 'x265', 'hevc', 'yify', 'yts', 'yts mx', 'yts am', 'ext', 'extended',
    'proper', 'repack', 'remastered', 'hdr', 'dv', 'dvdrip', '10bit', 'dts', 'ddp5', 'ddp', 'ddp2', 'aac',
    'silence', 'collection', 'complete', 'series', 'movie', 'shorts', 'amzn',
    'web-dl', 'elite', 'galaxytv', 'tgx', 'ctrlhd', 'hetteam', 'ntb', 'rartv',
    'cakes', 'h264', 'nf', 'atvp', 'hulu', '6ch', 'dd', 'dl',
    'mkv', 'mkvCage', 'judas', 'nogrp', 'successfulcrab', 'index', 'uindex',
    'www', 'org')

KEYWORD_OVERRIDES = {
    'bon temps': 'True Blood',
    'alan ball': 'True Blood',
    'authority confessionals': 'True Blood',
    'farewell to bon temps': 'True Blood',
    'hamiltons pharmacopeia': "Hamilton's Pharmacopeia",
    'anatomy of a scene': 'True Blood',
    'humans and vampires': 'True Blood',
    'true death': 'True Blood',
    'oh sookie': 'True Blood',
    'vampire report': 'True Blood',
    'final touches': 'True Blood',
    'the final touches': 'True Blood',
    'silicon valley': 'Silicon Valley',
    'hacker hostel': 'Silicon Valley',
    'techcrunch': 'Silicon Valley',
    'fun run': 'Regular Show',
    'ninja shoes': 'Regular Show',
    'pizza pouch': 'Regular Show',
    'ooohh': 'Regular Show',
    'customer service': 'Silicon Valley',
}


# --- Direct-Play Logic (copied from main.py) ---
DIRECT_PLAY_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".ogv"}

def can_direct_play(path: str) -> bool:
    """
    Checks if a file's extension is in the DIRECT_PLAY_EXTS set.
    """
    return os.path.splitext(path)[1].lower() in DIRECT_PLAY_EXTS

# --- Helper functions from scanner.py (copied and adapted for standalone use) ---
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

    year = None
    m = re.search(r'\b(19[0-9]{2}|20[0-9]{2}|202[0-9])\b', name)
    if m and not name.strip().isdigit():
        year = m.group(1)
        name = name[:m.start()].strip()

    name = re.sub(r'\b\d{1,2}$', '', name).strip()
    name = re.sub(r'\s+', ' ', name).strip()
    return name, year

def _is_noise_dir(name: str) -> bool:
    """Check if the directory name is noisy and should be skipped when finding the series folder."""
    name_lower = name.lower()
    if not name_lower:
        return False
    if re.match(r'(?i)^season[ _\-]?\d+', name_lower):
        return True
    if re.match(r'(?i)^s\d+', name_lower):
        return True
    if name_lower in ALL_DIR_BLACKLIST:
        return True
    if re.search(r'(?i)s\d{1,2}e\d{1,3}|\d{1,2}x\d{1,3}', name_lower):
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

def parse_tv_info(path: Path) -> dict | None:
    """Parse TV show episode info from path. Return None if not TV-like.
    This version focuses only on extracting the series name, and assumes standard SxxExx or folder structure."""
    filename = path.name.lower()
    patterns = [
        r'(?i)(?:^|[^a-z])s?(\d{1,2})[ex\- ](\d{1,3})(?:[^a-z]|$)',
        r'(?i)(\d{1,2})[x\- ](\d{1,3})',
        r'(?i)season[ _\-]?(\d{1,2}).*?extra[ _\-]?(\d{1,3})'
    ]
    
    # Check for SxxExx or xxbxx or season N extra NN patterns in filename
    is_episode_pattern_in_filename = any(re.search(pat, filename) for pat in patterns)

    # Figure out which folder represents the series
    show_dir = path.parent
    while _is_noise_dir(show_dir.name) and show_dir.parent != show_dir:
        show_dir = show_dir.parent
    
    # Get show name from directory
    show_name, year_hint = clean_filename(show_dir)

    # Fall back to filename if show_dir name is invalid or noisy
    if not show_name or len(show_name) < 3 or show_name.isdigit() or show_name.lower() in ALL_DIR_BLACKLIST or not re.search(r'[a-zA-Z]', show_name):
        base = path.stem
        base = re.sub(r'(?i)[._ -]*s\d{1,2}[ex]\d{1,3}.*', '', base)
        base = re.sub(r'(?i)[._ -]*\d{1,2}x\d{1,3}.*', '', base)
        base = re.sub(r'(?i)season\s*\d+\s*extra\s*\d+.*', '', base)
        base = re.sub(r'(?i)season\s*\d+.*', '', base)
        base = re.sub(r'(?i)extra\s*\d+.*', '', base)
        base = re.sub(r'(?i)\s*-\s*\d{1,4}\s*-\s*.*', '', base)
        base = _strip_junk_tokens(base)
        show_name, year_hint = clean_filename(Path(base))

    if not show_name or len(show_name) < 3 or not re.search(r'[a-zA-Z]', show_name):
        for anc in path.parents:
            cand, cand_year = clean_filename(anc)
            cand_lower = cand.lower().strip()
            if cand_lower in {'season'}:
                continue
            if cand and len(cand) >= 3 and not cand.isdigit() \
               and cand_lower not in ALL_DIR_BLACKLIST \
               and re.search(r'[a-zA-Z]', cand):
                show_name = cand
                if not year_hint:
                    year_hint = cand_year
                break

    show_name = _strip_junk_tokens(show_name)
    show_name = re.sub(r'(?i)\bseason\s*\d+(?:\s*-\s*\d+|\s+\d+)?\b', '', show_name)
    show_name = re.sub(r'(?i)\bs\d{1,2}(-s\d{1,2})?\b', '', show_name)
    show_name = re.sub(r'(?i)\bS\d{1,2}\b', '', show_name)
    show_name = re.sub(r'(?i)\b5[ _\.]?1\b', '', show_name)
    show_name = re.sub(r'\bsilence\b', '', show_name, flags=re.IGNORECASE)
    show_name = re.sub(r'\b\d{1,2}\b$', '', show_name).strip()
    show_name = re.sub(r'(?i)\bseason\b$', '', show_name).strip()
    show_name = re.sub(r'\s+', ' ', show_name).strip()

    show_name_lower = show_name.lower()
    for key, canonical in KEYWORD_OVERRIDES.items():
        if key in show_name_lower:
            show_name = canonical
            break
    if 'regular show' in show_name_lower:
        show_name = "Regular Show"
    if show_name_lower.startswith('the office'):
        show_name = "The Office"

    if not is_episode_pattern_in_filename and 'season' not in path.parent.name.lower():
        return None # Not a recognized episode
    
    return {
        "show": show_name,
        "year_hint": year_hint
    }

# ----------------------------------------------------------------------
def check_direct_playable_files():
    print(f"--- Checking Direct-Play compatibility ---")
    print(f"  Supported direct-play extensions: {', '.join(DIRECT_PLAY_EXTS)}")
    print("-" * 70)

    movie_direct_playable = []
    movie_transcode_only = []
    
    # Store compatibility for the first episode found for each series
    tv_series_compatibility = {} # { "Series Name": True/False (is_direct_playable) }
    
    for root_entry in SCAN_ROOTS:
        root_path = root_entry["path"]
        content_type = root_entry["type"]
        
        if not root_path.exists():
            print(f"Error: Directory '{root_path}' does not exist, skipping.")
            continue
            
        print(f"\nScanning '{root_path}' for {content_type}s…")
        
        for file_path in root_path.rglob("*"):
            if not is_video_file(file_path):
                continue
            
            abs_path = str(file_path.resolve())
            
            if content_type == "movie":
                relative_path = file_path.relative_to(root_path)
                if can_direct_play(abs_path):
                    movie_direct_playable.append(relative_path)
                else:
                    movie_transcode_only.append(relative_path)
            elif content_type == "tv":
                tv_info = parse_tv_info(file_path)
                if tv_info and tv_info["show"]:
                    series_name = tv_info["show"]
                    # Only check the first episode found for this series
                    if series_name not in tv_series_compatibility:
                        is_direct = can_direct_play(abs_path)
                        tv_series_compatibility[series_name] = is_direct
            
    print("\n--- Movie Files ---")
    if movie_direct_playable:
        print("\n  Direct-Playable Movies (Good Candidates):")
        for p in movie_direct_playable:
            print(f"  ✅ {p}")
    else:
        print("\n  No direct-playable movie files found based on extensions.")
        
    if movie_transcode_only:
        print("\n  Transcode-Only Movies (Will always be HLS):")
        for p in movie_transcode_only:
            print(f"  ❌ {p} (.{os.path.splitext(p)[1].lower()})")
    else:
        print("\n  All found movie files are direct-playable.")

    print("\n--- TV Series Compatibility (Based on First Episode Scanned) ---")
    if tv_series_compatibility:
        sorted_series = sorted(tv_series_compatibility.keys())
        for series_name in sorted_series:
            is_direct = tv_series_compatibility[series_name]
            status = "✅ Direct-Playable" if is_direct else "❌ Transcode-Only"
            print(f"  {status}: {series_name}")
        print("\nNote: Compatibility for TV series is determined by the first episode encountered. ")
        print("      It assumes all episodes in a series use similar encoding/container formats.")
    else:
        print("  No TV series found or recognized.")

    print("\n" + "=" * 70)
    print("Check complete. Use 'scanner.py' to add files to the database.")

if __name__ == "__main__":
    # Temporarily add project root to path to ensure modules can be found
    # (though this script is self-contained enough not to need it for its core logic)
    script_dir = Path(__file__).parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    check_direct_playable_files()