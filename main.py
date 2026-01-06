# main.py in media-server/
import os
import math
import shutil
import time
import asyncio
from typing import Optional, Dict
from fastapi.responses import StreamingResponse, FileResponse
import subprocess
import mimetypes
import requests
import sqlite3
from fastapi import FastAPI, HTTPException, Response, BackgroundTasks, Body, Query, Header, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from database import get_db_connection, initialize_db
from scanner import scan_and_update_library
import re
from auth import get_user_from_gateway, get_user_from_query
from history import router as history_router
from subtitles import router as sub_router
import logging
import json
import uuid
import requests
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
mimetypes.add_type("video/mp2t", ".ts")
mimetypes.add_type("text/vtt", ".vtt")

# --- Configuration Constants ---
LMS_PUBLIC_URL = os.getenv("LMS_PUBLIC_URL", "http://localhost:8000")
IDENTITY_SERVICE_URL = os.getenv("IDENTITY_SERVICE_URL", "http://localhost:8001")
HEARTBEAT_INTERVAL_MINUTES = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", 5))

active_processes = {}
SEGMENT_DURATION_SEC = 10
QUALITY_PRESETS = {'low': 28, 'medium': 23, 'high': 18}
RESOLUTION_PRESETS = {"source": None, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "eadf04bca50ce3477da06fffecca64e8a")
TMDB_BASE = "https://api.themoviedb.org/3"

# --- Hardware Acceleration Check ---
HWACCEL_MODE = os.getenv("HWACCEL_MODE", "auto").lower() # e.g., "auto", "qsv", "nvenc", "none"
HWACCEL_AVAILABLE = "none" # Default to none

def check_hwaccel():
    """Check for available hardware acceleration with a functional test."""
    global HWACCEL_AVAILABLE

    if HWACCEL_MODE == "none":
        logging.info("Hardware acceleration is explicitly disabled. Using CPU.")
        HWACCEL_AVAILABLE = "none"
        return

    # Check for NVIDIA NVENC with a functional test
    if HWACCEL_MODE in ["auto", "nvenc"]:
        try:
            # First, check if encoder is listed to avoid unnecessary test runs
            encoders_result = subprocess.run(['ffmpeg', '-v', 'quiet', '-encoders'], capture_output=True, text=True, check=True)
            if 'h264_nvenc' in encoders_result.stdout:
                # Now, perform a real (but quick) test transcode to null
                test_cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=1280x720:rate=30', '-c:v', 'h264_nvenc', '-preset', 'p5', '-f', 'null', '-']
                subprocess.run(test_cmd, capture_output=True, text=True, check=True, timeout=10)
                logging.info("SUCCESS: NVIDIA NVENC hardware acceleration is available and functional.")
                HWACCEL_AVAILABLE = "nvenc"
                return
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            logging.warning(f"NVENC check failed. It may be configured but not operational in this environment. Error: {e}")
            pass # Continue to next check

    # Check for Intel Quick Sync Video (QSV) with a functional test
    if HWACCEL_MODE in ["auto", "qsv"]:
         if os.path.exists("/dev/dri") and any("renderD" in s for s in os.listdir("/dev/dri")):
            try:
                encoders_result = subprocess.run(['ffmpeg', '-v', 'quiet', '-encoders'], capture_output=True, text=True, check=True)
                if 'h264_qsv' in encoders_result.stdout:
                    test_cmd = ['ffmpeg', '-y', '-hwaccel', 'qsv', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=1280x720:rate=30', '-c:v', 'h264_qsv', '-preset', 'veryfast', '-f', 'null', '-']
                    subprocess.run(test_cmd, capture_output=True, text=True, check=True, timeout=10)
                    logging.info("SUCCESS: Intel QSV hardware acceleration is available and functional.")
                    HWACCEL_AVAILABLE = "qsv"
                    return
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                logging.warning(f"QSV check failed. It may be configured but not operational. Error: {e}")

    logging.warning("No functional hardware acceleration (NVENC/QSV) detected or enabled. Falling back to CPU transcoding (libx264).")
    HWACCEL_AVAILABLE = "none"

# --- Path Translation Helper ---
def _get_path_mappings() -> Dict[str, str]:
    """Parses the PATH_MAPPINGS environment variable into a dictionary.
    Format: "HostPath1=>ContainerPath1,HostPath2=>ContainerPath2"
    Returns: A dictionary like {'c:/movies': '/media/movies'}
    """
    mappings_str = os.getenv("PATH_MAPPINGS", "")
    if not mappings_str:
        return {}
            
    mappings = {}
    for pair in mappings_str.split(','):
        if '=>' in pair:
            host_path, container_path = pair.split('=>', 1)
            normalized_host_path = host_path.strip().lower().replace('\\', '/')
            mappings[normalized_host_path] = container_path.strip()
    return mappings

PATH_MAPPINGS = _get_path_mappings()
if PATH_MAPPINGS:
    logging.info(f"Loaded path mappings for container: {PATH_MAPPINGS}")

def _translate_host_path(host_path: str) -> str:
    """Translates a host path to a container path if a mapping exists."""
    if not PATH_MAPPINGS:
        return host_path
            
    normalized_host_path = host_path.strip().lower().replace('\\', '/')
            
    best_match = ""
    for host_prefix in PATH_MAPPINGS.keys():
        if normalized_host_path.startswith(host_prefix):
            if len(host_prefix) > len(best_match):
                best_match = host_prefix
    
    if best_match:
        container_prefix = PATH_MAPPINGS[best_match]
        relative_path = normalized_host_path[len(best_match):]
        translated_path = os.path.join(container_prefix, relative_path.lstrip('/\\'))
        logging.info(f"Translated host path '{host_path}' to container path '{translated_path}'")
        return translated_path
                    
    logging.warning(f"No container mapping found for host path '{host_path}'. Using original path.")
    return host_path


# --- Sidecar Subtitle Helpers ---
SIDECAR_SUBTITLE_EXTS = {
    ".srt", ".vtt", ".ass", ".ssa", ".sub", ".smi", ".sup", ".idx"
}


def _normalize_for_match(name: str) -> str:
    # Remove punctuation/whitespace so "Movie.Title.2023" matches "Movie Title 2023.en"
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_sidecar_subtitles(video_path: str) -> List[dict]:
    """Return subtitle files that look associated with a given video.

    We keep this lightweight and filesystem-based (no DB), because the request is
    specifically about subtitle files living next to the media file.
    """
    try:
        vp = Path(video_path)
        if not vp.exists() or not vp.is_file():
            return []

        parent = vp.parent
        video_stem_norm = _normalize_for_match(vp.stem)

        subs: List[dict] = []
        all_subs: List[Path] = []
        video_exts = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".webm", ".ogv"}

        for child in parent.iterdir():
            if not child.is_file():
                continue

            if child.suffix.lower() in SIDECAR_SUBTITLE_EXTS:
                all_subs.append(child)
                # Basic "belongs to this file" heuristic
                if not _normalize_for_match(child.stem).startswith(video_stem_norm):
                    continue
            else:
                continue

            try:
                size_bytes = child.stat().st_size
            except OSError:
                size_bytes = None
            subs.append({
                "filename": child.name,
                "path": str(child),
                "size_bytes": size_bytes,
            })

        # Fallback: if nothing matched by filename, but the directory contains only
        # one video, treat all subtitle files in the folder as "associated".
        if not subs and all_subs:
            try:
                video_files = [p for p in parent.iterdir() if p.is_file() and p.suffix.lower() in video_exts]
            except OSError:
                video_files = []
            if len(video_files) == 1:
                for s in all_subs:
                    try:
                        size_bytes = s.stat().st_size
                    except OSError:
                        size_bytes = None
                    subs.append({
                        "filename": s.name,
                        "path": str(s),
                        "size_bytes": size_bytes,
                    })

        subs.sort(key=lambda x: x["filename"].lower())
        return subs
    except Exception as e:
        logging.warning(f"Failed to find sidecar subtitles for {video_path}: {e}")
        return []


def _assert_owner(user: dict):
    """Enforce owner-only access.

    Note: token-based auth via `get_user_from_query` depends on what the Identity
    Service returns from /auth/validate. Some deployments may omit `is_owner`.
    In that case, we conservatively *do not* block here (otherwise downloads
    would always 403).
    """
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if "is_owner" in user and not user.get("is_owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")


def _safe_join_same_dir(video_path: str, requested_name: str) -> Path:
    """Safely resolve `requested_name` to a file in the same directory as `video_path`."""
    vp = Path(video_path)
    parent = vp.parent.resolve()
    candidate = (parent / requested_name).resolve()
    if candidate.parent != parent:
        raise HTTPException(status_code=400, detail="Invalid subtitle filename")
    return candidate

# --- Segment Waiter Helper (with increased timeout) ---
async def wait_for_ready(path: str):
    MIN_SEG_BYTES = 32 * 1024
    STABILITY_CHECKS = 2
    POLL_INTERVAL_SEC = 0.25
    SEG_TIMEOUT_SEC = 120 # Increased timeout for slow transcodes

    start_time = time.time()
    stable_count = 0
    last_size = -1

    while True:
        if time.time() - start_time > SEG_TIMEOUT_SEC:
            raise FileNotFoundError(f"Segment not ready after {SEG_TIMEOUT_SEC}s: {path}")

        if os.path.exists(path):
            size = os.path.getsize(path)
            if size >= MIN_SEG_BYTES and size == last_size:
                stable_count += 1
                if stable_count >= STABILITY_CHECKS:
                    return # Segment is ready
            else:
                stable_count = 0
            last_size = size
        
        await asyncio.sleep(POLL_INTERVAL_SEC)

# --- Manifest Generator (Corrected and Final) ---
def generate_vod_manifest(duration_seconds: int, token: str):
    """
    Generates a complete HLS VOD manifest for the entire duration of the media.
    This is the correct approach for VOD playback, as it gives the player the
    full timeline context.
    """
    num_segments = math.ceil(duration_seconds / SEGMENT_DURATION_SEC)
    manifest_lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{SEGMENT_DURATION_SEC}",
        "#EXT-X-PLAYLIST-TYPE:VOD"
    ]

    for i in range(num_segments):
        segment_duration_at_end = min(SEGMENT_DURATION_SEC, duration_seconds - (i * SEGMENT_DURATION_SEC))
        if segment_duration_at_end <= 0:
             break
        manifest_lines.extend([
            f"#EXTINF:{segment_duration_at_end:.6f},",
            f"stream{i}.ts?token={token}"
        ])
    manifest_lines.append("#EXT-X-ENDLIST")
    return "\n".join(manifest_lines)

DIRECT_PLAY_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".ogv"}
SAFE_VIDEO_CODECS = {'h264'}
SAFE_AUDIO_CODECS = {'aac', 'mp3', 'opus'}
SAFE_AUDIO_CHANNELS = 2

def probe_media_file(file_path: str) -> dict:
    try:
        command = ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,channels', '-of', 'json', file_path]
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
                if channels is None:
                    channels = 6 
                codecs['a'] = {'name': audio_codec_name, 'channels': channels}
        return codecs
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        logging.error(f"ffprobe error for {file_path}: {e}")
        return {}

def can_direct_play(path: str) -> bool:
    container = os.path.splitext(path)[1].lower()
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
    audio_ok = (audio_codec in SAFE_AUDIO_CODECS and audio_channels is not None and audio_channels <= SAFE_AUDIO_CHANNELS) if audio_codec else False
        
    logging.info(f"Direct play check for '{os.path.basename(path)}': Video='{video_codec}' (safe: {video_ok}), Audio='{audio_codec}' @ {audio_channels}ch (safe: {audio_ok})")
        
    return video_ok and audio_ok

def range_streamer(file_path, start, end, size):
    with open(file_path, 'rb') as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk_size = min(1024 * 1024 * 2, remaining) 
            data = f.read(chunk_size)
            if not data:
                break 
            yield data
            remaining -= len(data)

# --- FFmpeg Runner (Corrected and Final) ---
def run_ffmpeg_sync(movie_id: int, video_path: str, hls_output_dir: str, seek_time: float, crf: int, scaling_filter: list, start_segment_number: int, burn_sub_path: Optional[str] = None):
    global active_processes, HWACCEL_AVAILABLE
    logging.info(f"[run_ffmpeg_sync] Starting for movie {movie_id}, output dir: {hls_output_dir}, seek: {seek_time}, start_segment: {start_segment_number}")

    # --- Probe file for audio and video codec info ---
    codecs = probe_media_file(video_path)
    video_codec = codecs.get('v')
    audio_info = codecs.get('a', {})
    audio_codec_name = audio_info.get('name')
    audio_channels = audio_info.get('channels', 2)

    # --- Basic Arguments ---
    seek_args = []
    if seek_time > 1:
        # Use -ss before -i for fast seeking
        seek_args = ['-ss', str(seek_time)]

    # Input file argument needs to be after seek
    input_args = ['-i', video_path]
    
    # --- Audio Transcoding Logic ---
    audio_args = []
    if audio_codec_name == 'aac' and audio_channels <= 2:
        logging.info(f"[run_ffmpeg_sync] Audio for {movie_id}: Copying existing AAC stereo track.")
        audio_args = ['-c:a', 'copy']
    else:
        target_channels = min(audio_channels or 2, 6) 
        bitrate = f"{128 * (target_channels // 2)}k" 
        logging.info(f"[run_ffmpeg_sync] Audio for {movie_id}: Transcoding to {target_channels}-channel AAC at {bitrate}.")
        audio_args = ['-c:a', 'aac', '-b:a', bitrate, '-ac', str(target_channels)]

    # --- Subtitle Burning Logic ---
    final_vf = []
    sub_filter_string = ""
    scale_filter_string = ""

    if burn_sub_path:
        # For Windows compatibility and path escaping, format path for ffmpeg filters.
        # This replaces backslashes with forward slashes and escapes characters like ':'
        sub_path_escaped = burn_sub_path.replace('\\', '/').replace(':', '\\\\:')
        sub_filter_string = f"subtitles='{sub_path_escaped}'"
        logging.info(f"[run_ffmpeg_sync] Burning in subtitles from: {burn_sub_path}")

    if scaling_filter:
        # scaling_filter is like ["-vf", "scale=..."]
        scale_filter_string = scaling_filter[1]

    # Chain the filters if both exist
    if sub_filter_string and scale_filter_string:
        final_vf = ["-vf", f"{scale_filter_string},{sub_filter_string}"]
    elif sub_filter_string:
        final_vf = ["-vf", sub_filter_string]
    elif scale_filter_string:
        final_vf = ["-vf", scale_filter_string]
        
    # --- Hardware Acceleration Command Logic (Decoding + Encoding) ---
    hw_input_args = []
    video_codec_args = []

    if HWACCEL_AVAILABLE == "nvenc":
        logging.info("[run_ffmpeg_sync] Using NVIDIA NVENC for transcoding.")
        # Attempt to use hardware decoding if source is h264 or hevc
        if video_codec == "h264":
            hw_input_args = ['-hwaccel', 'cuda', '-c:v', 'h264_cuvid']
        elif video_codec == "hevc":
            hw_input_args = ['-hwaccel', 'cuda', '-c:v', 'hevc_cuvid']
        
        # Use NVENC encoder with quality settings
        video_codec_args = ['-c:v', 'h264_nvenc', '-preset', 'p5', '-cq', str(crf)]
        if hw_input_args:
             logging.info(f"[run_ffmpeg_sync] Added HW decode args: {' '.join(hw_input_args)}")


    elif HWACCEL_AVAILABLE == "qsv":
        logging.info("[run_ffmpeg_sync] Using Intel QSV for transcoding.")
        hw_input_args = ['-hwaccel', 'qsv', '-qsv_device', '/dev/dri/renderD128']
        # Attempt to use hardware decoding for QSV
        if video_codec == "h264":
            hw_input_args.extend(['-c:v', 'h264_qsv'])
        elif video_codec == "hevc":
            hw_input_args.extend(['-c:v', 'hevc_qsv'])

        # Use QSV encoder with quality settings
        video_codec_args = ['-c:v', 'h264_qsv', '-preset', 'veryfast', '-global_quality', str(crf)]
        if len(hw_input_args) > 2:
             logging.info(f"[run_ffmpeg_sync] Added HW decode args: {' '.join(hw_input_args)}")

    else: # Fallback to CPU
        logging.info("[run_ffmpeg_sync] Using CPU (libx264) for transcoding.")
        video_codec_args = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(crf)]

    # --- Final Command Assembly ---
    ffmpeg_command = [
        'ffmpeg', '-hide_banner', *hw_input_args, *seek_args, *input_args,
        *final_vf,
        '-pix_fmt', 'yuv420p',
        *video_codec_args,
        *audio_args,
        '-f', 'segment',
        '-segment_time', str(SEGMENT_DURATION_SEC),
        '-segment_format', 'mpegts',
        '-segment_list_type', 'flat',
        '-segment_start_number', str(start_segment_number),
        '-sc_threshold', '0',
        '-force_key_frames', f"expr:gte(t,n_forced*{SEGMENT_DURATION_SEC})",
        '-g', str(int(24 * 4)), # GOP size, e.g., 4 seconds at 24fps
        'stream%d.ts'
    ]
    if not burn_sub_path:
        ffmpeg_command.insert(ffmpeg_command.index('-f'), '-sn')
        
    log_file_path = os.path.join(os.getcwd(), f"logs/ffmpeg_{movie_id}.log")
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_mode = "a" if seek_time > 1 else "w" 
    logging.info(f"[run_ffmpeg_sync] FFmpeg log file: {log_file_path}, mode: {log_mode}")
    logging.info(f"[run_ffmpeg_sync] Attempting to run FFmpeg command in cwd '{hls_output_dir}':")
    logging.info(f"[run_ffmpeg_sync] {' '.join(ffmpeg_command)}")

    with open(log_file_path, log_mode) as log_file:
        log_file.write(f"\n--- FFmpeg command for seek_time={seek_time:.2f}s, start_segment_number={start_segment_number}, crf={crf} ---\n")
        log_file.write(" ".join(ffmpeg_command) + "\n\n")
        log_file.flush() 
        
        process = None 
        try:
            process = subprocess.Popen(ffmpeg_command, stdout=log_file, stderr=subprocess.STDOUT, cwd=hls_output_dir)
            active_processes[movie_id] = {"process": process, "dir": hls_output_dir}
            logging.info(f"[run_ffmpeg_sync] Started FFmpeg (PID: {process.pid}) for movie {movie_id}. Waiting for it to finish...")
                        
            process.wait() 
                        
            logging.info(f"[run_ffmpeg_sync] FFmpeg process for movie {movie_id} (PID: {getattr(process, 'pid', 'N/A')}) has finished. Exit code: {process.returncode}")
            if process.returncode != 0:
                logging.error(f"[run_ffmpeg_sync] FFmpeg process for movie {movie_id} exited with non-zero code {process.returncode}. Check {log_file_path} for full FFmpeg output.")
            else:
                logging.info(f"[run_ffmpeg_sync] FFmpeg process for movie {movie_id} completed successfully.")

        except FileNotFoundError:
            logging.error(f"[run_ffmpeg_sync] FFmpeg executable not found. Ensure FFmpeg is installed and in your system's PATH.")
        except Exception as e:
            logging.error(f"[run_ffmpeg_sync] An unexpected error occurred while running FFmpeg for movie {movie_id}: {e}", exc_info=True)
            if process and process.poll() is None: 
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    logging.warning(f"[run_ffmpeg_sync] Killed unresponsive FFmpeg process after error for movie {movie_id}.")
        finally:
            if movie_id in active_processes:
                del active_processes[movie_id]
            logging.info(f"[run_ffmpeg_sync] Cleanup: Process for movie {movie_id} removed from active_processes.")

async def send_heartbeat(server_unique_id: str):
    """Sends a single heartbeat to the Identity Service."""
    try:
        response = requests.post(
            f"{IDENTITY_SERVICE_URL}/servers/heartbeat",
            json={"server_unique_id": server_unique_id, "url": LMS_PUBLIC_URL},
            timeout=10
        )
        response.raise_for_status()
        logging.info(f"Heartbeat sent successfully (URL: {LMS_PUBLIC_URL}).")
    except requests.RequestException as e:
        logging.error(f"Heartbeat failed: {e}")

async def heartbeat_task(server_unique_id: str):
    """Periodically sends a heartbeat."""
    while True:
        await asyncio.sleep(60 * HEARTBEAT_INTERVAL_MINUTES)
        await send_heartbeat(server_unique_id)

async def lifespan(app: FastAPI):
    # Startup logic
    print("Server starting up...")
    check_hwaccel() # Check for hardware acceleration on startup
    initialize_db()
    hls_base_dir = os.path.join("static", "hls")
    if os.path.exists(hls_base_dir):
        shutil.rmtree(hls_base_dir)         
        logging.info(f"Cleared old HLS cache directory: {hls_base_dir}")
    os.makedirs(hls_base_dir, exist_ok=True)        
    print(f"Using configured LMS_PUBLIC_URL: {LMS_PUBLIC_URL}")        
    conn = get_db_connection()    
    cursor = conn.cursor()        
    cursor.execute("SELECT value FROM server_config WHERE key = 'server_unique_id'")
    unique_id_row = cursor.fetchone()
    if not unique_id_row:
        server_unique_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO server_config (key, value) VALUES ('server_unique_id', ?)", (server_unique_id,))
        conn.commit()
        print(f"Generated new server_unique_id: {server_unique_id}")
    else:
        server_unique_id = unique_id_row['value']
        print(f"Existing server_unique_id found: {server_unique_id}")        
    try:        
        response = requests.post(f"{IDENTITY_SERVICE_URL}/servers/generate-claim-token", json={"server_id": server_unique_id}, timeout=10)        
        response.raise_for_status()        
        claim_token_data = response.json()        
        claim_token = claim_token_data.get("claim_token")                
        cursor.execute("INSERT OR REPLACE INTO server_config (key, value) VALUES ('claim_token', ?)", (claim_token,))        
        conn.commit()                
        print("\n" + "="*50)
        # NOTE: keep console output ASCII-only for smooth Windows dev experience
        # (default Windows codepages can raise UnicodeEncodeError on emojis).
        print("Your Lantern Media Server is running!")
        print("To link this server to your account, enter the following details in the web UI:")        
        print(f"  - Server URL:    {LMS_PUBLIC_URL}")        
        print(f"  - Claim Token:   {claim_token}")        
        print("="*50 + "\n")    
    except requests.RequestException as e:        
        print("\n--- !!! CRITICAL STARTUP ERROR !!! ---")        
        print(f"Could not get claim token from the Identity Service: {e}")        
        print(f"Is the Identity Service running at {IDENTITY_SERVICE_URL}? ")        
        print("--------------------------------------\n")    
    finally:        
        conn.close()
    print(f"Sending initial heartbeat for server {server_unique_id} with URL {LMS_PUBLIC_URL}")    
    asyncio.create_task(send_heartbeat(server_unique_id))    
    asyncio.create_task(heartbeat_task(server_unique_id))
    yield 
    # Shutdown logic
    print("Server shutting down...")
    global active_processes
    for movie_id, process_info in list(active_processes.items()):
        process = process_info.get("process")
        if process:
            logging.info(f"Terminating FFmpeg process (PID: {process.pid}) for movie {movie_id} during shutdown.")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                logging.warning(f"Killed unresponsive FFmpeg process for movie {movie_id} during shutdown.")
    print("All processes terminated.")

app = FastAPI(title="Project Lantern", lifespan=lifespan)

origins_from_env_str = os.getenv("ALLOWED_ORIGINS", "https://lantern.henosis.us,http://localhost:5173")
configured_origins = [o.strip() for o in origins_from_env_str.split(',') if o.strip()]
logging.info(f"CORS middleware configured with origins: {configured_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class HLSStaticFiles(StaticFiles):    
    """    
    Custom StaticFiles handler to wait for .ts segments to be ready    
    before serving them, which is crucial for HLS transcoding.    
    """    
    async def get_response(self, path: str, scope):        
        if path.endswith(".ts"):            
            full_path = os.path.join(self.directory, path)            
            logging.info(f"[HLSStaticFiles] Request for {path}. Full path: {full_path}")            
            try:                
                await wait_for_ready(full_path)                
                logging.info(f"[HLSStaticFiles] Segment {path} is ready.")            
            except FileNotFoundError as e:                
                logging.error(f"[HLSStaticFiles] Segment {path} NOT ready (timeout or file missing). Error: {e}")                
                return Response(status_code=404, content="Segment not found or not ready.")                
        resp = await super().get_response(path, scope)        
        if path.endswith(".vtt") or path.endswith(".ts"):            
            logging.info(f"[STATIC] {scope['method']} /static/{path} -> {resp.status_code}")        
        return resp

app.mount("/static", HLSStaticFiles(directory="static"), name="static")

app.include_router(history_router, dependencies=[Depends(get_user_from_gateway)])
app.include_router(sub_router, dependencies=[Depends(get_user_from_gateway)])

@app.get("/")
def read_root():
    return {"Project": "Lantern", "Status": "Running"}

@app.post("/library/scan")
def trigger_scan(background_tasks: BackgroundTasks, current_user=Depends(get_user_from_gateway)):
    background_tasks.add_task(scan_and_update_library)
    return {"message": "Library scan started in the background."}

@app.get("/library/movies")
def get_movies(current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    movies = conn.execute("SELECT id, title, overview, poster_path, duration_seconds, tmdb_id, parent_id FROM movies ORDER BY title").fetchall()
    conn.close()
    return [dict(movie) for movie in movies]

@app.patch("/library/movies/{movie_id}/parent")
def set_parent(movie_id: int, parent_id: int = Body(embed=True), current_user=Depends(get_user_from_gateway)):
    if movie_id == parent_id:
        raise HTTPException(status_code=400, detail="movie_id and parent_id cannot be the same")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM movies WHERE id = ?", (parent_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="parent_id not found")
    cur.execute("UPDATE movies SET parent_id=? WHERE id=?", (parent_id, movie_id))
    conn.commit()
    conn.close()
    return {"status": "ok", "movie_id": movie_id, "parent_id": parent_id}

@app.get("/library/movies/{movie_id}/details")
def movie_details(movie_id: int, current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    row = conn.execute("SELECT id, title, overview, poster_path, duration_seconds, tmdb_id, filepath, vote_average, genres, video_codec, audio_codec, is_direct_play FROM movies WHERE id=?", (movie_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Movie not found")
    movie_data = dict(row)
    if movie_data['overview'] is None and movie_data['tmdb_id'] is not None:
        try:
            # Placeholder for tmdb_details - you need to implement this or import from a correct file
            def tmdb_details(tmdb_id_val: int) -> dict:
                try:
                    url = f"{TMDB_BASE}/movie/{tmdb_id_val}?api_key={TMDB_API_KEY}"
                    response = requests.get(url, timeout=5)
                    response.raise_for_status()
                    return response.json()
                except requests.RequestException as e:
                    logging.error(f"Failed to fetch TMDB details for ID {tmdb_id_val}: {e}")
                    return {}

            tmdb_data = tmdb_details(movie_data['tmdb_id'])
            overview = tmdb_data.get('overview')
            if overview:
                conn.execute("UPDATE movies SET overview = ? WHERE id = ?", (overview, movie_id))
                conn.commit()
                movie_data['overview'] = overview
        except Exception as e:
            logging.error(f"TMDb fetch error for movie {movie_id}: {e}")
    conn.close()
    return movie_data


@app.get("/library/movies/{movie_id}/sidecar_subtitles")
def movie_sidecar_subtitles(movie_id: int, current_user=Depends(get_user_from_gateway)):
    """Owner-only: list subtitle files living next to the movie file."""
    _assert_owner(current_user)
    conn = get_db_connection()
    row = conn.execute("SELECT filepath FROM movies WHERE id=?", (movie_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Movie not found")
    return [
        {"filename": s["filename"], "size_bytes": s.get("size_bytes")}
        for s in find_sidecar_subtitles(row["filepath"])
    ]

@app.get("/library/series/{series_id}/details")
def series_details(series_id: int, current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    row = conn.execute("SELECT id, title, overview, poster_path, first_air_date, vote_average, genres FROM series WHERE id=?", (series_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Series not found")
    return dict(row)


@app.get("/library/episodes/{episode_id}/details")
def episode_details(episode_id: int, current_user=Depends(get_user_from_gateway)):
    """Owner-only: file + tech info for a single episode."""
    _assert_owner(current_user)
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT e.id, e.series_id, e.season, e.episode, e.title, e.filepath, e.duration_seconds,
               e.video_codec, e.audio_codec, e.is_direct_play
        FROM episodes e
        WHERE e.id=?
        """,
        (episode_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Episode not found")
    return dict(row)


@app.get("/library/episodes/{episode_id}/sidecar_subtitles")
def episode_sidecar_subtitles(episode_id: int, current_user=Depends(get_user_from_gateway)):
    """Owner-only: list subtitle files living next to the episode file."""
    _assert_owner(current_user)
    conn = get_db_connection()
    row = conn.execute("SELECT filepath FROM episodes WHERE id=?", (episode_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Episode not found")
    return [
        {"filename": s["filename"], "size_bytes": s.get("size_bytes")}
        for s in find_sidecar_subtitles(row["filepath"])
    ]


@app.get("/library/series/{series_id}/episodes/tech")
def series_episodes_tech(series_id: int, current_user=Depends(get_user_from_gateway)):
    """Owner-only: list episodes including file + codec info.

    This is intended for the "Files & Tech Info" admin modal in the UI.
    """
    _assert_owner(current_user)
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, season, episode, title, filepath, duration_seconds,
               video_codec, audio_codec, is_direct_play
        FROM episodes
        WHERE series_id=?
        ORDER BY season, episode
        """,
        (series_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/tmdb/search")
def proxy_tmdb_search(q: str, year: Optional[str] = None, current_user=Depends(get_user_from_gateway)):
    # Placeholder for tmdb_search - you need to implement this or import from a correct file
    def tmdb_search(query: str, year: Optional[str] = None) -> dict:
        try:
            params = {"api_key": TMDB_API_KEY, "query": query}
            if year:
                params["year"] = year
            url = f"{TMDB_BASE}/search/movie"
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"Failed to search TMDB for query '{query}': {e}")
            return {"results": []}

    return tmdb_search(q, year)

@app.post("/library/movies/{movie_id}/set_tmdb")
def set_tmdb(movie_id: int, tmdb_id: int = Body(embed=True), current_user=Depends(get_user_from_gateway)):
    # Re-using tmdb_details from above or assuming it's correctly imported
    data = tmdb_details(tmdb_id)
    genres_list = [genre['name'] for genre in data.get('genres', [])]
    genres_str = ", ".join(genres_list) if genres_list else None
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE movies SET tmdb_id=?, title=?, overview=?, poster_path=?, release_date=?, vote_average=?, genres=?, parent_id=NULL WHERE id=?", (tmdb_id, data.get("title"), data.get("overview"), data.get("poster_path"), data.get("release_date"), data.get("vote_average"), genres_str, movie_id))
    conn.commit()
    conn.close()
    return {"status": "ok", "movie_id": movie_id, "tmdb_id": tmdb_id}

@app.get("/direct/{movie_id}")
def direct_stream(movie_id: int, request: Request, item_type: str = Query("movie"), current_user=Depends(get_user_from_query)):
    conn = get_db_connection()
    if item_type == "episode":
        row = conn.execute("SELECT filepath FROM episodes WHERE id = ?", (movie_id,)).fetchone()
    else:
        row = conn.execute("SELECT filepath FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"{item_type.capitalize()} not found")

    file_path = row["filepath"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File missing on disk")

    media_type, _ = mimetypes.guess_type(file_path)
    media_type = media_type or "application/octet-stream"

    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end_str = match.group(2)
            size = os.path.getsize(file_path)
            end = min(int(end_str), size - 1) if end_str else size - 1

            if start > end or start < 0 or end >= size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
                        
            length = end - start + 1
            return StreamingResponse(
                range_streamer(file_path, start, end, size),
                status_code=206,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Content-Length": str(length),
                    "Accept-Ranges": "bytes",
                    "Content-Type": media_type
                }
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid range header format")
    else:
        return FileResponse(path=file_path, media_type=media_type, filename=os.path.basename(file_path))


@app.get("/download/movie/{movie_id}")
def download_movie(movie_id: int, current_user=Depends(get_user_from_query)):
    """Download the original movie file (attachment). Token-auth via query parameter."""
    _assert_owner(current_user)
    conn = get_db_connection()
    row = conn.execute("SELECT filepath FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Movie not found")

    file_path = row["filepath"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File missing on disk")

    media_type, _ = mimetypes.guess_type(file_path)
    media_type = media_type or "application/octet-stream"
    return FileResponse(path=file_path, media_type=media_type, filename=os.path.basename(file_path))


@app.get("/download/movie/{movie_id}/subtitle/{filename}")
def download_movie_sidecar_subtitle(movie_id: int, filename: str, current_user=Depends(get_user_from_query)):
    """Download a sidecar subtitle file for a movie (attachment)."""
    _assert_owner(current_user)
    conn = get_db_connection()
    row = conn.execute("SELECT filepath FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Movie not found")

    # Validate filename is an allowed, associated sidecar subtitle
    allowed = {s["filename"] for s in find_sidecar_subtitles(row["filepath"])}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Subtitle not found")

    sub_path = _safe_join_same_dir(row["filepath"], filename)
    if not sub_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle missing on disk")

    media_type, _ = mimetypes.guess_type(str(sub_path))
    media_type = media_type or "application/octet-stream"
    return FileResponse(path=str(sub_path), media_type=media_type, filename=sub_path.name)


@app.get("/download/episode/{episode_id}")
def download_episode(episode_id: int, current_user=Depends(get_user_from_query)):
    """Download the original episode file (attachment). Token-auth via query parameter."""
    _assert_owner(current_user)
    conn = get_db_connection()
    row = conn.execute("SELECT filepath FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Episode not found")

    file_path = row["filepath"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File missing on disk")

    media_type, _ = mimetypes.guess_type(file_path)
    media_type = media_type or "application/octet-stream"
    return FileResponse(path=file_path, media_type=media_type, filename=os.path.basename(file_path))


@app.get("/download/episode/{episode_id}/subtitle/{filename}")
def download_episode_sidecar_subtitle(episode_id: int, filename: str, current_user=Depends(get_user_from_query)):
    """Download a sidecar subtitle file for an episode (attachment)."""
    _assert_owner(current_user)
    conn = get_db_connection()
    row = conn.execute("SELECT filepath FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Episode not found")

    allowed = {s["filename"] for s in find_sidecar_subtitles(row["filepath"])}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Subtitle not found")

    sub_path = _safe_join_same_dir(row["filepath"], filename)
    if not sub_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle missing on disk")

    media_type, _ = mimetypes.guess_type(str(sub_path))
    media_type = media_type or "application/octet-stream"
    return FileResponse(path=str(sub_path), media_type=media_type, filename=sub_path.name)

@app.get("/stream/{movie_id}")
async def start_stream(request: Request, movie_id: int, seek_time: float = 0, prefer_direct: bool = Query(False), force_transcode: bool = Query(False), quality: str = Query("medium"), scale: str = Query("source"), subtitle_id: Optional[int] = Query(None), burn: bool = Query(False), item_type: str = Query("movie"), current_user=Depends(get_user_from_gateway)):
    global active_processes
    logging.info(f"[start_stream] --- New Request ---")
    logging.info(f"[start_stream] Movie ID: {movie_id}, Seek: {seek_time}, Item Type: {item_type}")
    logging.info(f"[start_stream] Quality: {quality}, Scale: {scale}")
    logging.info(f"[start_stream] Subtitle ID: {subtitle_id}, Burn: {burn}, Force Transcode: {force_transcode}")

    # Existing process termination logic
    if movie_id in active_processes:
        proc_info = active_processes.pop(movie_id)
        proc = proc_info.get("process")
        if proc:
            logging.info(f"[start_stream] Terminating existing FFmpeg process (PID: {proc.pid}) for movie {movie_id}.")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                logging.warning(f"[start_stream] Killed unresponsive FFmpeg process for movie {movie_id}.")
        # Clean up old HLS output directory
        if os.path.exists(proc_info["dir"]):
            try:
                shutil.rmtree(proc_info["dir"])
                logging.info(f"[start_stream] Removed old HLS directory: {proc_info['dir']}")
            except OSError as e:
                logging.error(f"[start_stream] Error removing old HLS directory {proc_info['dir']}: {e}")
    else:
        logging.info(f"[start_stream] No active FFmpeg process found for movie {movie_id} to terminate.")

    conn = get_db_connection()
    if item_type == "episode":
        item = conn.execute("SELECT filepath, duration_seconds FROM episodes WHERE id = ?", (movie_id,)).fetchone()
    else:
        item = conn.execute("SELECT filepath, duration_seconds FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()

    if not item:
        raise HTTPException(status_code=404, detail=f"{item_type.capitalize()} not found")
    video_path, duration = item['filepath'], item['duration_seconds']
    logging.info(f"[start_stream] Video path: {video_path}")

    # Subtitle processing
    sub_path, soft_sub_url = None, None
    if subtitle_id is not None:
        logging.info(f"[start_stream] Processing subtitle_id: {subtitle_id}")
        sub_conn = get_db_connection()
        if item_type == "movie":
            sub_row = sub_conn.execute("SELECT file_path FROM subtitles WHERE id = ? AND movie_id = ?", (subtitle_id, movie_id)).fetchone()
        else: # item_type == "episode"
            sub_row = sub_conn.execute("SELECT file_path FROM episode_subtitles WHERE id = ? AND episode_id = ?", (subtitle_id, movie_id)).fetchone()
        sub_conn.close()

        if not sub_row:
            logging.error(f"[start_stream] Subtitle with id {subtitle_id} not found for item {movie_id}.")
            raise HTTPException(status_code=404, detail="Subtitle not found for this item.")
                
        full_sub_path = sub_row["file_path"]
        logging.info(f"[start_stream] Found subtitle path in DB: {full_sub_path}")
        
        if burn:
            force_transcode = True # Must transcode to burn in subtitles
            sub_path = os.path.abspath(full_sub_path)
            logging.info(f"[start_stream] Burn-in requested. Absolute subtitle path: {sub_path}")
            if not os.path.exists(sub_path):
                logging.error(f"[start_stream] Subtitle file for burning does not exist at: {sub_path}")
                raise HTTPException(status_code=404, detail="Subtitle file not found on disk.")
        else:
            soft_sub_url = f"/static/{full_sub_path}?token={current_user['token']}"
            soft_sub_url = soft_sub_url.replace('\\', '/')
            logging.info(f"[start_stream] Soft subtitle URL generated: {soft_sub_url}")
    else:
        logging.info("[start_stream] No subtitle_id provided.")

    # Determine if direct play is possible and preferred
    if not force_transcode and prefer_direct and scale == "source" and can_direct_play(video_path):
        item_type_param = f"&item_type={item_type}" if item_type == "episode" else ""
        direct_url = f"/direct/{movie_id}?token={current_user['token']}{item_type_param}"
        logging.info(f"[start_stream] Direct play enabled. Returning direct_url: {direct_url}")
        return {
            "mode": "direct",
            "direct_url": direct_url,
            "duration_seconds": duration,
            "soft_sub_url": soft_sub_url         
        }

    # Transcoding required
    logging.info("[start_stream] Transcoding required.")
    try:
        crf = QUALITY_PRESETS[quality] if quality in QUALITY_PRESETS else int(quality)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid quality parameter")

    if scale not in RESOLUTION_PRESETS:
        raise HTTPException(status_code=400, detail=f"Invalid scale. Allowed: {', '.join(RESOLUTION_PRESETS)}")
        
    target_height = RESOLUTION_PRESETS[scale]
    scaling_filter = []
    if target_height:
        scaling_filter = ["-vf", f"scale=-2:'min({target_height},ih)'"]
        logging.info(f"[start_stream] Scaling filter applied: {scaling_filter}")

    session_id = str(int(time.time() * 1000000))     
    hls_output_dir = os.path.join("static", "hls", str(movie_id), session_id)
    os.makedirs(hls_output_dir, exist_ok=True)
    active_processes[movie_id] = {"process": None, "dir": hls_output_dir}
    logging.info(f"[start_stream] New HLS output directory created: {hls_output_dir}")

    # Calculate the starting segment number for FFmpeg's benefit (performance)
    start_segment_number_for_ffmpeg = math.floor(seek_time / SEGMENT_DURATION_SEC) if seek_time > 0 else 0
    logging.info(f"[start_stream] Calculated start_segment_number for FFmpeg: {start_segment_number_for_ffmpeg} for seek_time: {seek_time}")
    
    manifest_path = os.path.join(hls_output_dir, "stream.m3u8")        
    # IMPORTANT: Call generate_vod_manifest WITHOUT the start_segment_number.
    # This ensures a full playlist is always created for the player's timeline.
    manifest_content = generate_vod_manifest(duration, current_user['token'])
    with open(manifest_path, "w") as f:
        f.write(manifest_content)
    logging.info(f"[start_stream] Full HLS manifest written to: {manifest_path}")

    # Launch FFmpeg as a background task, passing the correct start_segment_number for FFmpeg.    
    logging.info(f"[start_stream] Launching FFmpeg for movie {movie_id} as background task...")
    asyncio.create_task(asyncio.to_thread(        
        run_ffmpeg_sync,        
        movie_id,        
        video_path,        
        hls_output_dir,        
        seek_time, # This is the actual seek_time for -ss        
        crf,        
        scaling_filter,        
        start_segment_number_for_ffmpeg, # This is the crucial arg for FFmpeg's segment numbering        
        burn_sub_path=sub_path     
    ))
    logging.info(f"[start_stream] FFmpeg task scheduled.")

    playlist_url = f"/static/hls/{movie_id}/{session_id}/stream.m3u8?token={current_user['token']}"
    logging.info(f"[start_stream] Returning HLS playlist URL: {playlist_url}")
    return {        
        "hls_playlist_url": playlist_url,        
        "crf_used": crf,        
        "resolution_used": scale,        
        "duration_seconds": duration,         
        "soft_sub_url": soft_sub_url     
    }

@app.delete("/stream/{movie_id}")
def stop_stream(movie_id: int, current_user=Depends(get_user_from_gateway)):
    global active_processes
    logging.info(f"[stop_stream] Request received to stop stream for movie_id: {movie_id}")
    if movie_id in active_processes:
        proc_info = active_processes.pop(movie_id)
        proc = proc_info.get("process")
        if proc:
            logging.info(f"[stop_stream] Terminating FFmpeg process (PID: {proc.pid}) for movie {movie_id} via DELETE request.")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                logging.warning(f"[stop_stream] Killed unresponsive FFmpeg process for movie {movie_id} via DELETE request.")
        if os.path.exists(proc_info["dir"]):
            try:
                shutil.rmtree(proc_info["dir"])
                logging.info(f"[stop_stream] Removed HLS directory: {proc_info['dir']}")
            except OSError as e:
                logging.error(f"[stop_stream] Error removing HLS directory {proc_info['dir']}: {e}")
    else:
        logging.info(f"[stop_stream] No active FFmpeg process found for movie {movie_id} to terminate.")
    return Response(status_code=204) 

@app.get("/library/series")
def list_series(current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    rows = conn.execute("SELECT id, title, overview, poster_path, first_air_date FROM series ORDER BY title").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/library/series/{series_id}/episodes")
def list_episodes(series_id: int, season: Optional[int] = None, current_user=Depends(get_user_from_gateway)):
    cols = "id, season, episode, title, overview, duration_seconds, air_date, extra_type, still_path"
    conn = get_db_connection()
    if season is None:
        rows = conn.execute(f"SELECT {cols} FROM episodes WHERE series_id = ? ORDER BY season, episode", (series_id,)).fetchall()
    else:
        rows = conn.execute(f"SELECT {cols} FROM episodes WHERE series_id = ? AND season = ? ORDER BY episode", (series_id, season)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/server/claim-info")
def get_claim_info():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM server_config WHERE key = 'claim_token'")
    claim_token_row = cursor.fetchone()
    conn.close()
    claim_token = claim_token_row['value'] if claim_token_row else None
    if not claim_token:
        raise HTTPException(status_code=404, detail="Claim token not available. Server might already be claimed.")
    return {"server_url": LMS_PUBLIC_URL, "claim_token": claim_token}

@app.get("/server/status")
def server_status(current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM server_config WHERE key = 'server_unique_id'")
    unique_id_row = cursor.fetchone()
    cursor.execute("SELECT value FROM server_config WHERE key = 'claim_token'")
    claim_token_row = cursor.fetchone()
    conn.close()
    server_unique_id = unique_id_row['value'] if unique_id_row else None
    claim_token = claim_token_row['value'] if claim_token_row else None
    is_claimed = claim_token is None     
    return {"is_claimed": is_claimed, "claim_token": claim_token if not is_claimed else None}

@app.post("/libraries", status_code=201)
def create_library(library: dict = Body(..., embed=True), current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    cursor = conn.cursor()            
    original_path = library['path']
    container_path = _translate_host_path(original_path)            
    try:        
        cursor.execute("INSERT INTO libraries (name, path, type) VALUES (?, ?, ?)", (library['name'], container_path, library['type']))        
        conn.commit()        
        library_id = cursor.lastrowid        
        return {"id": library_id, "name": library['name'], "path": container_path, "type": library['type']}    
    except sqlite3.IntegrityError:        
        conn.close()        
        raise HTTPException(status_code=409, detail="Library name must be unique")    
    finally:        
        conn.close()

@app.get("/libraries")
def list_libraries(current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, path, type FROM libraries")
    libraries = cursor.fetchall()
    conn.close()
    return [dict(lib) for lib in libraries]

@app.delete("/libraries/{id}")
def delete_library(id: int, current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM libraries WHERE id = ?", (id,))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Library not found")
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/sharing/invite")
def share_invite(invite_request: dict = Body(..., embed=True), current_user: dict = Depends(get_user_from_gateway)):
    if not current_user.get("is_owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the server owner can share access.")        
    identity_service_payload = {        
        "server_unique_id": invite_request.get("server_unique_id"),         
        "invitee_username": invite_request.get("invitee_identifier"),         
        "resource_type": "full_access",         
        "resource_id": "*"     
    }
    if not identity_service_payload["server_unique_id"] or not identity_service_payload["invitee_username"]:        
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing server_unique_id or invitee_identifier in the request body.")        
    try:        
        response = requests.post(f"{IDENTITY_SERVICE_URL}/sharing/invite", json=identity_service_payload)        
        response.raise_for_status()         
        return response.json()    
    except requests.RequestException as e:        
        if e.response is not None:            
            raise HTTPException(status_code=e.response.status_code, detail=e.response.json().get("detail"))        
        raise HTTPException(status_code=502, detail=f"Could not connect to Identity Service: {str(e)}")
