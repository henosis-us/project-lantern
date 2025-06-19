import os
import math
import shutil
import time
import asyncio
from fastapi.responses import StreamingResponse
import subprocess
import mimetypes
import requests
from fastapi import FastAPI, HTTPException, Response, BackgroundTasks, Body, Query, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.requests import Request
from database import get_db_connection, initialize_db
from scanner import scan_and_update_library
import re
from auth import router as auth_router, get_current_user
from history import router as history_router
from subtitles import router as sub_router  # New import for subtitles router
import logging
import json  # NEW: Import json for parsing ffprobe output

# Register MIME type for .ts and .vtt files
mimetypes.add_type("video/mp2t", ".ts")
mimetypes.add_type("text/vtt", ".vtt")  # Added for VTT subtitle support

# --- START: Added code to load .env file ---
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
# --- END: Added code ---

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# --- Segment Waiter Helper ---
async def wait_for_ready(path: str):
    """
    Asynchronously waits for a segment file to be size-stable and above minimum size.
    """
    MIN_SEG_BYTES = 32 * 1024  # 32 kB
    STABILITY_CHECKS = 2       # Must be unchanged for this many consecutive loops
    POLL_INTERVAL_SEC = 0.25
    SEG_TIMEOUT_SEC = 60       # Fail if the encoder is stuck
    start_time = time.time()
    stable_count = 0
    last_size = -1
    while True:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size >= MIN_SEG_BYTES and size == last_size:
                stable_count += 1
                if stable_count >= STABILITY_CHECKS:
                    return  # Segment is ready and stable
            else:
                stable_count = 0  # Reset stability count if size changes or too small
            last_size = size
        if time.time() - start_time > SEG_TIMEOUT_SEC:
            raise FileNotFoundError(f"Segment not ready after {SEG_TIMEOUT_SEC}s: {path}")
        await asyncio.sleep(POLL_INTERVAL_SEC)

active_processes = {}  # Global dictionary to track active processes

# --- Configuration Constants ---
SEGMENT_DURATION_SEC      = 10      # seconds per .ts chunk (updated)
INITIAL_BUFFER_SECONDS    = 30      # how much video we want ready before we reply (3 segments)
SEEK_WAIT_TIMEOUT_SECONDS = 20      # timeout when seeking
SEEK_BUFFER_SEGMENTS      = 5       # number of segments to buffer for seeks

# --- Quality Presets for Transcode ---
QUALITY_PRESETS = {
    'low': 28,
    'medium': 23,
    'high': 18,
}

# --- Resolution Presets for Transcode ---
RESOLUTION_PRESETS = {
    "source": None,   # None  -> keep original
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

# --- TMDb Configuration ---
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "eadf04bca50ce347da06fffecca64e8a")
TMDB_BASE = "https://api.themoviedb.org/3"

# ───────── owner configuration ─────────
OWNER_USERNAMES = set(os.getenv("LIBRARY_OWNERS", "henosis").split(","))

def require_owner(user = Depends(get_current_user)):
    if user["username"] not in OWNER_USERNAMES:
        raise HTTPException(status_code=403, detail="Owner privileges required")
    return user

def tmdb_search(query: str, year: str | None = None):
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

def generate_vod_manifest(duration_seconds: int):
    num_segments = math.ceil(duration_seconds / SEGMENT_DURATION_SEC)
    manifest_lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{SEGMENT_DURATION_SEC}",
        "#EXT-X-PLAYLIST-TYPE:VOD"
    ]
    for i in range(num_segments):
        manifest_lines.extend([f"#EXTINF:{SEGMENT_DURATION_SEC:.6f},", f"stream{i}.ts"])
    manifest_lines.append("#EXT-X-ENDLIST")
    return "\n".join(manifest_lines)

# --- NEW: Direct-Play Helper with Codec Checking ---
DIRECT_PLAY_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".ogv"}
SAFE_VIDEO_CODECS = {'h264'}  # Browser-safe video codecs
SAFE_AUDIO_CODECS = {'aac', 'mp3', 'opus'}  # Browser-safe audio codecs
SAFE_AUDIO_CHANNELS = 2  # Max channels for direct play (stereo)

def probe_media_file(file_path: str) -> dict:
    """
    Runs ffprobe on a media file to get video and audio stream information.
    Returns a dictionary with 'v' for video codec and 'a' for audio info.
    """
    try:
        command = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=codec_type,codec_name,channels',
            '-select_streams', 'v:0,a:0',  # Select first video and first audio stream
            '-of', 'json', file_path
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        probe_data = json.loads(result.stdout)

        if not probe_data or 'streams' not in probe_data:
            return {}

        codecs = {}
        for stream in probe_data['streams']:
            codec_type = stream.get('codec_type')
            if codec_type == 'video' and 'v' not in codecs:
                codecs['v'] = stream.get('codec_name')
            elif codec_type == 'audio' and 'a' not in codecs:
                codecs['a'] = {
                    'name': stream.get('codec_name'),
                    'channels': stream.get('channels')
                }
        return codecs

    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"ffprobe failed for {file_path}: {e}")
        return {}

def can_direct_play(path: str) -> bool:
    """
    Checks if a media file's codecs are suitable for direct playback in a web browser.
    """
    # First, check the container extension (e.g., avoid MKV)
    container = os.path.splitext(path)[1].lower()
    if container not in {".mp4", ".m4v", ".webm"}:
        return False

    # Probe for actual codecs
    codecs = probe_media_file(path)
    if not codecs:
        logging.warning(f"Could not probe codecs for {path}, assuming transcode is needed.")
        return False

    video_codec = codecs.get('v')
    audio_info = codecs.get('a', {})
    audio_codec = audio_info.get('name')
    audio_channels = audio_info.get('channels')

    # Check if codecs are in the safe list
    video_ok = video_codec in SAFE_VIDEO_CODECS if video_codec else False
    audio_ok = (
        audio_codec in SAFE_AUDIO_CODECS and
        audio_channels is not None and
        audio_channels <= SAFE_AUDIO_CHANNELS
    ) if audio_codec else False  # If no audio, it's not safe for media playback

    logging.info(
        f"Direct play check for '{os.path.basename(path)}': "
        f"Video='{video_codec}' (safe: {video_ok}), "
        f"Audio='{audio_codec}' @ {audio_channels}ch (safe: {audio_ok})"
    )

    return video_ok and audio_ok

def range_streamer(file_path, start, end, size):
    with open(file_path, 'rb') as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk_size = min(1024 * 1024 * 2, remaining)  # 2MB chunks
            data = f.read(chunk_size)
            if not data:
                break
            yield data
            remaining -= len(data)

def run_ffmpeg_sync(movie_id: int, video_path: str, hls_output_dir: str, seek_time: float, end_time: float, crf: int, scaling_filter: list, burn_sub_path: str | None = None):
    global active_processes
    seek_args = []
    if seek_time > 1:
        seek_args = ['-ss', str(seek_time), '-avoid_negative_ts', 'make_zero']

    # --- NEW: Dynamic Audio Transcoding Logic using probe_media_file ---
    codecs = probe_media_file(video_path)  # Updated to use probe_media_file
    audio_info = codecs.get('a', {})
    codec_name = audio_info.get('name')
    channels = audio_info.get('channels')

    audio_args = []
    # If audio is already simple AAC and stereo or less, copy it directly.
    # Otherwise, transcode to web-safe AAC.
    if codec_name == 'aac' and channels and channels <= 2:
        logging.info(f"Audio for {movie_id}: Copying existing AAC stereo track.")
        audio_args = ['-c:a', 'copy']
    else:
        # Downmix to 5.1 (6 channels) if source has more, otherwise keep original. Default to 2.
        target_channels = min(channels or 2, 6)
        # Set bitrate based on channels (e.g., 128k for stereo, 384k for 5.1)
        bitrate = f"{128 * (target_channels // 2)}k"
        logging.info(f"Audio for {movie_id}: Transcoding to {target_channels}-channel AAC at {bitrate}.")
        audio_args = ['-c:a', 'aac', '-b:a', bitrate, '-ac', str(target_channels)]

    keyframe_args = [
        '-force_key_frames', f"expr:gte(t,n_forced*{SEGMENT_DURATION_SEC})",
        '-g', str(int(SEGMENT_DURATION_SEC * 24)),
        '-keyint_min', str(int(SEGMENT_DURATION_SEC * 24))
    ]
    subs_filter = []
    if burn_sub_path:
        subs_filter = ["-vf", f"subtitles={burn_sub_path}"]

    ffmpeg_command = [
        'ffmpeg', *seek_args, '-to', str(end_time), '-i', video_path,
        *subs_filter,
        *keyframe_args,
        *scaling_filter,
        '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(crf),
        *audio_args,  # Use the new dynamic audio arguments
        '-sn', '-f', 'segment',
        '-segment_time', str(SEGMENT_DURATION_SEC),
        '-segment_format', 'mpegts',
        '-segment_list_type', 'flat',
        '-segment_start_number', '0',  # Always start numbering from 0
        '-sc_threshold', '0', 'stream%d.ts'
    ]

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

# Define the lifespan handler
async def lifespan(app: FastAPI):
    # Startup logic
    print("Server starting up...")
    hls_base_dir = os.path.join("static", "hls")
    if os.path.exists(hls_base_dir):
        shutil.rmtree(hls_base_dir)
    os.makedirs(hls_base_dir, exist_ok=True)
    initialize_db()
    yield  # Yield control to the app
    # Shutdown logic
    print("Server shutting down. Terminating all active FFmpeg processes...")
    global active_processes  # Declare global to ensure access
    for movie_id, process_info in list(active_processes.items()):
        process = process_info.get("process")
        if process:  # Add guard to avoid errors if process is None
            print(f"  -> Terminating process for movie_id {movie_id} (PID: {process.pid})")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    print("All processes terminated.")

# Create the app with lifespan
app = FastAPI(title="Project Lantern", lifespan=lifespan)

# --- Custom StaticFiles class for waiting on HLS segments ---
class HLSStaticFiles(StaticFiles):
    """
    • For normal files we behave exactly like StaticFiles.
    • For any *.ts request we will block (async-sleep loop) until the
      encoder has produced a file that is both present and size-stable.
      This prevents the player from snow-balling 404s when it eagerly
      asks for segments that are not finished yet.
    """
    async def get_response(self, path: str, scope):
        # Only add waiting logic for transport stream segments
        if path.endswith(".ts"):
            full_path = os.path.join(self.directory, path)
            try:
                # wait_for_ready raises FileNotFoundError on timeout
                await wait_for_ready(full_path)
            except FileNotFoundError:
                # Fall through – StaticFiles will return 404
                pass

        # Hand off to the normal StaticFiles machinery
        resp = await super().get_response(path, scope)

        # Optional logging (handy for diagnostics)
        if path.endswith(".vtt") or path.endswith(".ts"):
            logging.info(f"[STATIC] {scope['method']} /static/{path} → {resp.status_code}")
        return resp

app.mount("/static", HLSStaticFiles(directory="static"), name="static")  # Updated mount with HLS waiting logic
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(sub_router)  # New: Include the subtitles router

@app.get("/")
def read_root():
    return {"Project": "Lantern", "Status": "Running"}

@app.post("/library/scan")
def trigger_scan(background_tasks: BackgroundTasks, _u = Depends(require_owner)):
    background_tasks.add_task(scan_and_update_library)
    return {"message": "Library scan started in the background."}

@app.get("/library/movies")
def get_movies():
    conn = get_db_connection()
    movies = conn.execute(
        """
        SELECT id, title, overview, poster_path, duration_seconds,
               tmdb_id, parent_id
        FROM movies
        ORDER BY title
        """
    ).fetchall()
    conn.close()
    return [dict(movie) for movie in movies]

@app.patch("/library/movies/{movie_id}/parent")
def set_parent(movie_id: int, parent_id: int = Body(embed=True), _u = Depends(require_owner)):
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

@app.get("/tmdb/search")
def proxy_tmdb_search(q: str, year: str | None = None):
    try:
        results = tmdb_search(q, year)
        return results
    except HTTPException as e:
        raise e

@app.post("/library/movies/{movie_id}/set_tmdb")
def set_tmdb(movie_id: int, tmdb_id: int = Body(embed=True), _u = Depends(require_owner)):
    try:
        data = tmdb_details(tmdb_id)
    except HTTPException as e:
        raise e

    # Extract and format genres
    genres_list = [genre['name'] for genre in data.get('genres', [])]
    genres_str = ", ".join(genres_list) if genres_list else None

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE movies
        SET tmdb_id=?, title=?, overview=?, poster_path=?, release_date=?, 
            vote_average=?, genres=?, parent_id=NULL
        WHERE id=?
        """,
        (
            tmdb_id,
            data.get("title"),
            data.get("overview"),
            data.get("poster_path"),
            data.get("release_date"),
            data.get("vote_average"),
            genres_str,
            movie_id,
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "movie_id": movie_id, "tmdb_id": tmdb_id}

# --- New Endpoint for Movie Details ---
@app.get("/library/movies/{movie_id}/details")
def movie_details(movie_id: int):
    conn = get_db_connection()
    # Select all the new columns for the details view
    row = conn.execute(
        """
        SELECT 
            id, title, overview, poster_path, duration_seconds, tmdb_id,
            filepath, vote_average, genres, video_codec, audio_codec, is_direct_play
        FROM movies 
        WHERE id=?
        """,
        (movie_id,)
    ).fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Movie not found")

    movie_data = dict(row)

    # Optional: If overview is NULL and tmdb_id is available, fetch from TMDb and cache in DB
    if movie_data['overview'] is None and movie_data['tmdb_id'] is not None:
        try:
            tmdb_data = tmdb_details(movie_data['tmdb_id'])
            overview = tmdb_data.get('overview')
            if overview:
                conn.execute("UPDATE movies SET overview = ? WHERE id = ?", (overview, movie_id))
                conn.commit()
                movie_data['overview'] = overview  # Update the dict in memory
        except Exception as e:
            print(f"TMDb fetch error for movie {movie_id}: {e}")  # Log error but continue
    
    conn.close()
    return movie_data

# --- Modified Direct-Play Endpoint with Range Support ---
@app.get("/direct/{movie_id}")
def direct_stream(movie_id: int, request: Request, item_type: str = Query("movie")):
    """
    Streams the raw file with HTTP Range support.
    """
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
        # Parse range header, e.g., "bytes=0-1023"
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end_str = match.group(2)
            size = os.path.getsize(file_path)
            if end_str:
                end = min(int(end_str), size - 1)
            else:
                end = size - 1
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
                    "Content-Type": media_type,
                }
            )
        else:
            return Response(status_code=400, detail="Invalid range")
    else:
        # No range, send full file
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=os.path.basename(file_path),
        )

@app.get("/stream/{movie_id}")
async def start_stream(request: Request, movie_id: int, seek_time: float = 0, prefer_direct: bool = Query(False), force_transcode: bool = Query(False), quality: str = Query("medium"), scale: str = Query("source"), subtitle_id: int | None = Query(None), burn: bool = Query(False), item_type: str = Query("movie")):
    global active_processes
    if movie_id in active_processes:
        logging.info(f"Terminating existing process for movie_id {movie_id} to handle new request.")
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
    video_path = item['filepath']
    duration = item['duration_seconds']
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
    sub_path = None
    soft_sub_url = None
    if subtitle_id is not None:
        sub_conn = get_db_connection()
        if item_type == "movie":
            sub_row = sub_conn.execute("SELECT file_path FROM subtitles WHERE id = ? AND movie_id = ?", (subtitle_id, movie_id)).fetchone()
        else:
            sub_row = sub_conn.execute("SELECT file_path FROM episode_subtitles WHERE id = ? AND episode_id = ?", (subtitle_id, movie_id)).fetchone()
        sub_conn.close()
        if not sub_row:
            raise HTTPException(status_code=404, detail="Subtitle not found for this item.")
        full_sub_path = os.path.join("static", sub_row["file_path"])
        if burn:
            force_transcode = True
            sub_path = full_sub_path
        else:
            soft_sub_url = str(request.base_url).rstrip("/") + f"/static/{sub_row['file_path']}"
    if not force_transcode and prefer_direct and scale == "source" and can_direct_play(video_path):
        item_type_param = f"?item_type={item_type}" if item_type == "episode" else ""
        direct_url = str(request.base_url).rstrip('/') + f"/direct/{movie_id}{item_type_param}"
        return {"mode": "direct", "direct_url": direct_url, "duration_seconds": duration, "soft_sub_url": soft_sub_url}
    encode_upto = min(duration, seek_time + 15 * 60)
    session_id = str(time.time()).replace(".", "")
    hls_output_dir = os.path.join("static", "hls", str(movie_id), session_id)
    os.makedirs(hls_output_dir, exist_ok=True)
    active_processes[movie_id] = {"process": None, "dir": hls_output_dir}
    manifest_path = os.path.join(hls_output_dir, "stream.m3u8")
    manifest_content = generate_vod_manifest(duration)
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
                if not os.path.exists(path):
                    all_ready = False
                    break
                size = os.path.getsize(path)
                if size < min_size_bytes or size != prev_sizes[i]:
                    all_ready = False
                prev_sizes[i] = size
            if all_ready:
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0
            if time.time() - start_time > timeout_sec:
                raise HTTPException(status_code=504, detail="Timed out waiting for buffer to stabilize and meet size requirements")
            await asyncio.sleep(0.25)
    segments_to_buffer = math.ceil(INITIAL_BUFFER_SECONDS / SEGMENT_DURATION_SEC)
    # Always wait for the first 3 segments (stream0.ts, stream1.ts, stream2.ts), regardless of seek_time
    segment_paths = [os.path.join(hls_output_dir, f"stream{i}.ts") for i in range(segments_to_buffer)]
    logging.info(f"Waiting for initial segments 0-{segments_to_buffer-1}...")
    await wait_size_stable(segment_paths, SEEK_WAIT_TIMEOUT_SECONDS if seek_time > 0 else INITIAL_BUFFER_SECONDS * 2)
    logging.info("Initial buffer ready.")
    playlist_url = f"/static/hls/{movie_id}/{session_id}/stream.m3u8"
    return {"hls_playlist_url": playlist_url, "crf_used": crf, "resolution_used": scale, "soft_sub_url": soft_sub_url}

@app.delete("/stream/{movie_id}")
def stop_stream(movie_id: int):
    global active_processes
    if movie_id in active_processes:
        logging.info(f"Received request to stop transcode for movie_id {movie_id}.")
        proc_info = active_processes.pop(movie_id)
        proc = proc_info.get("process")
        if proc:
            proc.terminate()
            logging.info(f"Process for movie_id {movie_id} terminated.")
    return Response(status_code=204)

# ──────────────────────  NEW LIBRARY ENDPOINTS  ──────────────────────
@app.get("/library/series")
def list_series():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, title, overview, poster_path, first_air_date
          FROM series
      ORDER BY title
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/library/series/{series_id}/episodes")
def list_episodes(series_id: int, season: int | None = None):
    """
    Retrieve a list of episodes for a given series ID. If a season is specified,
    return only episodes from that season; otherwise, return all episodes ordered by season and episode.
    """
    cols = (
        "id, season, episode, title, overview, duration_seconds, "
        "air_date, extra_type, still_path"
    )
    conn = get_db_connection()
    if season is None:
        rows = conn.execute(
            f"SELECT {cols} FROM episodes "
            "WHERE series_id = ? ORDER BY season, episode",
            (series_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {cols} FROM episodes "
            "WHERE series_id = ? AND season = ? ORDER BY episode",
            (series_id, season)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]