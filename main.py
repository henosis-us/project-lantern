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
from fastapi import FastAPI, HTTPException, Response, BackgroundTasks, Body, Query, Header, Depends
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

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
mimetypes.add_type("video/mp2t", ".ts")
mimetypes.add_type("text/vtt", ".vtt")

# --- Configuration Constants ---
LMS_PUBLIC_URL = os.getenv("LMS_PUBLIC_URL", "http://localhost:8000")
IDENTITY_SERVICE_URL = os.getenv("IDENTITY_SERVICE_URL", "http://localhost:8001")
HEARTBEAT_INTERVAL_MINUTES = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", 5))

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

# --- Segment Waiter Helper ---
async def wait_for_ready(path: str):
    MIN_SEG_BYTES = 32 * 1024
    STABILITY_CHECKS = 2
    POLL_INTERVAL_SEC = 0.25
    SEG_TIMEOUT_SEC = 60
    start_time = time.time()
    stable_count = 0
    last_size = -1
    while True:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size >= MIN_SEG_BYTES and size == last_size:
                stable_count += 1
                if stable_count >= STABILITY_CHECKS:
                    return
            else:
                stable_count = 0
            last_size = size
        if time.time() - start_time > SEG_TIMEOUT_SEC:
            raise FileNotFoundError(f"Segment not ready after {SEG_TIMEOUT_SEC}s: {path}")
        await asyncio.sleep(POLL_INTERVAL_SEC)

active_processes = {}
SEGMENT_DURATION_SEC = 10
INITIAL_BUFFER_SECONDS = 30
SEEK_WAIT_TIMEOUT_SECONDS = 20
SEEK_BUFFER_SEGMENTS = 5

QUALITY_PRESETS = {'low': 28, 'medium': 23, 'high': 18}
RESOLUTION_PRESETS = {"source": None, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360}

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "eadf04bca50ce347da06fffecca64e8a")
TMDB_BASE = "https://api.themoviedb.org/3"

def tmdb_search(query: str, year: Optional[str] = None):
    params = {"api_key": TMDB_API_KEY, "query": query}
    if year:
        params["year"] = year
    try:
        r = requests.get(f"{TMDB_BASE}/search/movie", params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("results", [])
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"TMDb search error: {e}")

def tmdb_details(tmdb_id: int):
    params = {"api_key": TMDB_API_KEY}
    try:
        r = requests.get(f"{TMDB_BASE}/movie/{tmdb_id}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"TMDb details error: {e}")

# MODIFIED: Accept a token to append to segment URLs
def generate_vod_manifest(duration_seconds: int, token: str):
    num_segments = math.ceil(duration_seconds / SEGMENT_DURATION_SEC)
    manifest_lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{SEGMENT_DURATION_SEC}", "#EXT-X-PLAYLIST-TYPE:VOD"]
    for i in range(num_segments):
        # MODIFIED: Append the token to each segment's URL
        manifest_lines.extend([f"#EXTINF:{SEGMENT_DURATION_SEC:.6f},", f"stream{i}.ts?token={token}"])
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

def run_ffmpeg_sync(movie_id: int, video_path: str, hls_output_dir: str, seek_time: float, end_time: float, crf: int, scaling_filter: list, burn_sub_path: Optional[str] = None):
    global active_processes
    seek_args = []
    if seek_time > 1:
        seek_args = ['-ss', str(seek_time), '-avoid_negative_ts', 'make_zero']
    codecs = probe_media_file(video_path)
    audio_info = codecs.get('a', {})
    codec_name = audio_info.get('name')
    channels = audio_info.get('channels')
    audio_args = []
    if codec_name == 'aac' and channels and channels <= 2:
        logging.info(f"Audio for {movie_id}: Copying existing AAC stereo track.")
        audio_args = ['-c:a', 'copy']
    else:
        target_channels = min(channels or 2, 6)
        bitrate = f"{128 * (target_channels // 2)}k"
        logging.info(f"Audio for {movie_id}: Transcoding to {target_channels}-channel AAC at {bitrate}.")
        audio_args = ['-c:a', 'aac', '-b:a', bitrate, '-ac', str(target_channels)]
    keyframe_args = ['-force_key_frames', f"expr:gte(t,n_forced*{SEGMENT_DURATION_SEC})", '-g', str(int(SEGMENT_DURATION_SEC * 24)), '-keyint_min', str(int(SEGMENT_DURATION_SEC * 24))]
    subs_filter = []
    if burn_sub_path:
        subs_filter = ["-vf", f"subtitles={burn_sub_path}"]
    ffmpeg_command = ['ffmpeg', *seek_args, '-to', str(end_time), '-i', video_path, *subs_filter, *keyframe_args, *scaling_filter, '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(crf), *audio_args, '-sn', '-f', 'segment', '-segment_time', str(SEGMENT_DURATION_SEC), '-segment_format', 'mpegts', '-segment_list_type', 'flat', '-segment_start_number', '0', '-sc_threshold', '0', 'stream%d.ts']
    os.makedirs("logs", exist_ok=True)
    log_file_path = os.path.join(os.getcwd(), f"logs/ffmpeg_{movie_id}.log")
    log_mode = "a" if seek_time > 1 else "w"
    with open(log_file_path, log_mode) as log_file:
        log_file.write(f"\n--- FFmpeg command for seek_time={seek_time:.2f}s, end_time={end_time:.2f}s, crf={crf} ---\n")
        log_file.write(" ".join(ffmpeg_command) + "\n\n")
        log_file.flush()
        try:
            process = subprocess.Popen(ffmpeg_command, stdout=log_file, stderr=subprocess.STDOUT, cwd=hls_output_dir)
            active_processes[movie_id] = {"process": process, "dir": hls_output_dir}
            logging.info(f"Started FFmpeg (PID: {process.pid}) for movie {movie_id} at seek time {seek_time:.2f}s.")
            process.wait()
        except Exception as e:
            logging.error(f"FFmpeg failed to start for movie {movie_id}: {e}")
            if movie_id in active_processes:
                del active_processes[movie_id]
    if movie_id in active_processes:
        del active_processes[movie_id]
    logging.info(f"FFmpeg process for movie {movie_id} (seek time {seek_time:.2f}s) has finished.")

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
    initialize_db()
    hls_base_dir = os.path.join("static", "hls")
    if os.path.exists(hls_base_dir):
        shutil.rmtree(hls_base_dir)
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
        print("🚀 Your Lantern Media Server is running!")
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
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    print("All processes terminated.")

app = FastAPI(title="Project Lantern", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://lantern.henosis.us"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class HLSStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if path.endswith(".ts"):
            full_path = os.path.join(self.directory, path)
            try:
                await wait_for_ready(full_path)
            except FileNotFoundError:
                pass
        resp = await super().get_response(path, scope)
        if path.endswith(".vtt") or path.endswith(".ts"):
            logging.info(f"[STATIC] {scope['method']} /static/{path} → {resp.status_code}")
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

@app.get("/library/series/{series_id}/details")
def series_details(series_id: int, current_user=Depends(get_user_from_gateway)):
    conn = get_db_connection()
    row = conn.execute("SELECT id, title, overview, poster_path, first_air_date, vote_average, genres FROM series WHERE id=?", (series_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Series not found")
    return dict(row)

@app.get("/tmdb/search")
def proxy_tmdb_search(q: str, year: Optional[str] = None, current_user=Depends(get_user_from_gateway)):
    return tmdb_search(q, year)

@app.post("/library/movies/{movie_id}/set_tmdb")
def set_tmdb(movie_id: int, tmdb_id: int = Body(embed=True), current_user=Depends(get_user_from_gateway)):
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
            return StreamingResponse(range_streamer(file_path, start, end, size), status_code=206, headers={"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length), "Accept-Ranges": "bytes", "Content-Type": media_type})
        else:
            return Response(status_code=400, detail="Invalid range")
    else:
        return FileResponse(path=file_path, media_type=media_type, filename=os.path.basename(file_path))

@app.get("/stream/{movie_id}")
async def start_stream(request: Request, movie_id: int, seek_time: float = 0, prefer_direct: bool = Query(False), force_transcode: bool = Query(False), quality: str = Query("medium"), scale: str = Query("source"), subtitle_id: Optional[int] = Query(None), burn: bool = Query(False), item_type: str = Query("movie"), current_user=Depends(get_user_from_gateway)):
    global active_processes
    if movie_id in active_processes:
        proc_info = active_processes.pop(movie_id)
        proc = proc_info.get("process")
        if proc:
            proc.terminate()
    conn = get_db_connection()
    if item_type == "episode":
        item = conn.execute("SELECT filepath, duration_seconds FROM episodes WHERE id = ?", (movie_id,)).fetchone()
    else:
        item = conn.execute("SELECT filepath, duration_seconds FROM movies WHERE id = ?", (movie_id,)).fetchone()
    conn.close()
    if not item:
        raise HTTPException(status_code=404, detail=f"{item_type.capitalize()} not found")
    video_path, duration = item['filepath'], item['duration_seconds']
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
        force_transcode = True
    sub_path, soft_sub_url = None, None
    if subtitle_id is not None:
        sub_conn = get_db_connection()
        if item_type == "movie":
            sub_row = sub_conn.execute("SELECT file_path FROM subtitles WHERE id = ? AND movie_id = ?", (subtitle_id, movie_id)).fetchone()
        else:
            sub_row = sub_conn.execute("SELECT file_path FROM episode_subtitles WHERE id = ? AND episode_id = ?", (subtitle_id, movie_id)).fetchone()
        sub_conn.close()
        if not sub_row:
            raise HTTPException(status_code=404, detail="Subtitle not found for this item.")
        full_sub_path = sub_row["file_path"]
        if burn:
            force_transcode = True
            sub_path = os.path.join(os.getcwd(), full_sub_path)
        else:
            soft_sub_url = f"/{full_sub_path}?token={current_user['token']}"
            
    if not force_transcode and prefer_direct and scale == "source" and can_direct_play(video_path):
        item_type_param = f"&item_type={item_type}" if item_type == "episode" else ""
        direct_url = f"/direct/{movie_id}?token={current_user['token']}{item_type_param}"
        return {"mode": "direct", "direct_url": direct_url, "duration_seconds": duration, "soft_sub_url": soft_sub_url}
        
    encode_upto = min(duration, seek_time + 15 * 60)
    session_id = str(time.time()).replace(".", "")
    hls_output_dir = os.path.join("static", "hls", str(movie_id), session_id)
    os.makedirs(hls_output_dir, exist_ok=True)
    active_processes[movie_id] = {"process": None, "dir": hls_output_dir}
    manifest_path = os.path.join(hls_output_dir, "stream.m3u8")
    
    # MODIFIED: Pass the token to the manifest generator
    manifest_content = generate_vod_manifest(duration, current_user['token'])
    with open(manifest_path, "w") as f:
        f.write(manifest_content)
        
    asyncio.create_task(asyncio.to_thread(run_ffmpeg_sync, movie_id, video_path, hls_output_dir, seek_time, encode_upto, crf, scaling_filter, burn_sub_path=sub_path if burn else None))
    async def wait_size_stable(paths, timeout_sec, min_size_bytes=32768):
        start_time = time.time()
        prev_sizes = [0] * len(paths)
        stable_count = 0
        while True:
            all_ready = True
            for i, path in enumerate(paths):
                if not os.path.exists(path) or os.path.getsize(path) < min_size_bytes or os.path.getsize(path) != prev_sizes[i]:
                    all_ready = False
                prev_sizes[i] = os.path.getsize(path) if os.path.exists(path) else 0
            if all_ready:
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0
            if time.time() - start_time > timeout_sec:
                raise FileNotFoundError("Timed out waiting for buffer to stabilize")
            await asyncio.sleep(0.25)
    segments_to_buffer = math.ceil(INITIAL_BUFFER_SECONDS / SEGMENT_DURATION_SEC)
    segment_paths = [os.path.join(hls_output_dir, f"stream{i}.ts") for i in range(segments_to_buffer)]
    await wait_size_stable(segment_paths, SEEK_WAIT_TIMEOUT_SECONDS if seek_time > 0 else INITIAL_BUFFER_SECONDS * 2)
    
    playlist_url = f"/static/hls/{movie_id}/{session_id}/stream.m3u8?token={current_user['token']}"
    
    return {"hls_playlist_url": playlist_url, "crf_used": crf, "resolution_used": scale, "soft_sub_url": soft_sub_url}

@app.delete("/stream/{movie_id}")
def stop_stream(movie_id: int, current_user=Depends(get_user_from_gateway)):
    global active_processes
    if movie_id in active_processes:
        proc_info = active_processes.pop(movie_id)
        proc = proc_info.get("process")
        if proc:
            proc.terminate()
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
        raise HTTPException(status_code=404, detail="Claim token not available.")
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
    identity_service_payload = {"server_unique_id": invite_request.get("server_unique_id"), "invitee_username": invite_request.get("invitee_identifier"), "resource_type": "full_access", "resource_id": "*"}
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