# subtitles.py
"""FastAPI router for all subtitle-related operations:
- Listing locally cached subtitles.
- Searching for new subtitles on OpenSubtitles.
- Downloading and caching selected subtitles.
"""
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Body, HTTPException, status, Query
from auth import get_user_from_gateway  # FIXED: Changed from get_current_user to get_user_from_gateway
from database import get_db_connection
import opensubtitles

# --- Router Setup ---
router = APIRouter(prefix="/subtitles", tags=["subtitles"])
SUBTITLES_DIR = Path("static/subtitles")
MOVIE_SUB_DIR = SUBTITLES_DIR / "movie"
EPISODE_SUB_DIR = SUBTITLES_DIR / "episode"
MOVIE_SUB_DIR.mkdir(parents=True, exist_ok=True)
EPISODE_SUB_DIR.mkdir(parents=True, exist_ok=True)

# --- Endpoints ---

@router.get("/{media_id}", summary="List cached subtitles for an item")
def list_local_subtitles(media_id: int, item_type: str = Query(..., enum=["movie", "episode"]), current_user=Depends(get_user_from_gateway)):  # FIXED: Changed dependency
    conn = get_db_connection()
    if item_type == "movie":
        rows = conn.execute("SELECT id, lang, COALESCE(file_name, file_path) AS name FROM subtitles WHERE movie_id = ?", (media_id,)).fetchall()
        pref = conn.execute("SELECT subtitle_id FROM subtitle_prefs WHERE username=? AND movie_id=?", (current_user["username"], media_id)).fetchone()  # FIXED: Use current_user["username"]
        url_prefix = f"/static/subtitles/movie/{media_id}"
    else:  # episode
        rows = conn.execute("SELECT id, lang, COALESCE(file_name, file_path) AS name FROM episode_subtitles WHERE episode_id = ?", (media_id,)).fetchall()
        pref = conn.execute("SELECT subtitle_id FROM episode_subtitle_prefs WHERE username=? AND episode_id=?", (current_user["username"], media_id)).fetchone()  # FIXED: Use current_user["username"]
        url_prefix = f"/static/subtitles/episode/{media_id}"

    selected_id = pref["subtitle_id"] if pref else None
    conn.close()

    return [
        {
            "id": r["id"],
            "lang": r["lang"],
            "name": r["name"] or f"[{r['lang']}] subtitle {r['id']}",
            "url": f"{url_prefix}/{r['id']}.vtt",
            "selected": r["id"] == selected_id
        }
        for r in rows
    ]

@router.get("/{media_id}/search", summary="Search OpenSubtitles for an item")
def search_remote_subtitles(media_id: int, item_type: str = Query(..., enum=["movie", "episode"]), lang: str = "en", current_user=Depends(get_user_from_gateway)):  # FIXED: Changed dependency
    conn = get_db_connection()
    try:
        if item_type == "movie":
            movie = conn.execute("SELECT title, release_date FROM movies WHERE id = ?", (media_id,)).fetchone()
            if not movie:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
            year = movie["release_date"][:4] if movie["release_date"] else None
            results = opensubtitles.search_subs(movie["title"], year, lang)
        else:  # episode
            episode = conn.execute("""
                SELECT e.season, e.episode, s.title AS series_title, s.first_air_date
                FROM episodes e JOIN series s ON e.series_id = s.id
                WHERE e.id = ?
                """, (media_id,)).fetchone()
            if not episode:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
            year = episode["first_air_date"][:4] if episode["first_air_date"] else None
            results = opensubtitles.search_subs(
                title=episode["series_title"],
                year=year,
                lang=lang,
                season=episode["season"],
                episode=episode["episode"]
            )

        # Filter and simplify results for the frontend
        return [
            {
                "id": item["id"],
                "attributes": {
                    "language": item["attributes"]["language"],
                    "feature_details": item["attributes"].get("feature_details"),
                    "file_name": item["attributes"]["files"][0].get("file_name", "Unknown"),
                    "file_id": item["attributes"]["files"][0]["file_id"],
                }
            }
            for item in results if item.get("attributes", {}).get("files")
        ]
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    finally:
        conn.close()

@router.post("/{media_id}/download", summary="Download and cache a subtitle")
def download_subtitle(
    media_id: int,
    file_id: int = Body(embed=True),
    file_name: str = Body(embed=True),
    lang: str = Body(embed=True, default="en"),
    item_type: str = Body(..., embed=True),  # Note: Using Body as per your code; consider Query if it fits your API better
    current_user=Depends(get_user_from_gateway)  # FIXED: Changed dependency
):
    conn = get_db_connection()
    try:
        if item_type == "movie":
            table, id_col = "subtitles", "movie_id"
            sub_dir = MOVIE_SUB_DIR / str(media_id)
            url_prefix = f"/static/subtitles/movie/{media_id}"
        elif item_type == "episode":
            table, id_col = "episode_subtitles", "episode_id"
            sub_dir = EPISODE_SUB_DIR / str(media_id)
            url_prefix = f"/static/subtitles/episode/{media_id}"
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid item_type specified.")

        # Check if this exact subtitle is already downloaded
        existing = conn.execute(f"SELECT id FROM {table} WHERE {id_col} = ? AND provider_id = ?", (media_id, file_id)).fetchone()
        if existing:
            return {
                "id": existing["id"],
                "url": f"{url_prefix}/{existing['id']}.vtt",
                "message": "Subtitle already cached."
            }

        # 1. Get the temporary download link from OpenSubtitles
        download_url = opensubtitles.get_download_link(file_id)

        # 2. Insert into DB to get a unique local ID for the filename
        cursor = conn.cursor()
        # We need the ID before we can generate the path, but we need the path to insert.
        # So we insert a temporary path, get the ID, then update the path.
        cursor.execute(
            f"""INSERT INTO {table} ({id_col}, provider, provider_id, lang, file_name, file_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (media_id, "opensubtitles", file_id, lang, file_name, "temp")
        )
        local_sub_id = cursor.lastrowid
        
        # 3. Define local paths and final DB path
        sub_dir.mkdir(exist_ok=True)
        vtt_relative_path = Path(url_prefix.lstrip('/')) / f"{local_sub_id}.vtt"
        srt_path = sub_dir / f"{local_sub_id}.srt"
        vtt_path = sub_dir / f"{local_sub_id}.vtt"

        # 4. Update the row with the final path
        cursor.execute(f"UPDATE {table} SET file_path = ? WHERE id = ?", (vtt_relative_path.as_posix(), local_sub_id))
        conn.commit()
        
        # 5. Download the file and convert
        opensubtitles.download_sub_file(download_url, srt_path)
        opensubtitles.srt_to_vtt(srt_path, vtt_path)
        srt_path.unlink() # Clean up the original SRT file

    except Exception as e:
        conn.rollback()  # Rollback the DB insert if download/conversion fails
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to download or process subtitle: {str(e)}")
    finally:
        conn.close()

    return {
        "id": local_sub_id,
        "url": str(Path(url_prefix) / f"{local_sub_id}.vtt"),
        "message": "Subtitle downloaded successfully."
    }

@router.get("/{media_id}/current", summary="Current subtitle selection")
def current_subtitle(media_id: int, item_type: str = Query(..., enum=["movie", "episode"]), current_user=Depends(get_user_from_gateway)):  # FIXED: Changed dependency
    conn = get_db_connection()
    if item_type == "movie":
        row = conn.execute("SELECT subtitle_id FROM subtitle_prefs WHERE username=? AND movie_id=?", (current_user["username"], media_id)).fetchone()  # FIXED: Use current_user["username"]
    else:  # episode
        row = conn.execute("SELECT subtitle_id FROM episode_subtitle_prefs WHERE username=? AND episode_id=?", (current_user["username"], media_id)).fetchone()  # FIXED: Use current_user["username"]
    conn.close()
    return {"subtitle_id": row["subtitle_id"] if row else None}

@router.put("/{media_id}/select", summary="Select subtitle for this item")
def select_subtitle(
    media_id: int,
    item_type: str = Query(..., enum=["movie", "episode"]),
    subtitle_id: Optional[int] = Body(None, embed=True),
    current_user=Depends(get_user_from_gateway)  # FIXED: Changed dependency
):
    conn = get_db_connection()
    cur = conn.cursor()

    if item_type == "movie":
        prefs_table, id_col = "subtitle_prefs", "movie_id"
        subs_table = "subtitles"
    else:  # episode
        prefs_table, id_col = "episode_subtitle_prefs", "episode_id"
        subs_table = "episode_subtitles"

    if subtitle_id is not None:
        # Validate ownership
        ok = cur.execute(f"SELECT 1 FROM {subs_table} WHERE id=? AND {id_col}=?", (subtitle_id, media_id)).fetchone()
        if not ok:
            conn.close()
            raise HTTPException(status_code=404, detail="Subtitle not found or does not belong to this media item.")

        cur.execute(f"""
            INSERT INTO {prefs_table} (username, {id_col}, subtitle_id)
            VALUES (?,?,?)
            ON CONFLICT(username, {id_col})
            DO UPDATE SET subtitle_id=excluded.subtitle_id
        """, (current_user["username"], media_id, subtitle_id))  # FIXED: Use current_user["username"]
    else:
        cur.execute(f"DELETE FROM {prefs_table} WHERE username=? AND {id_col}=?", (current_user["username"], media_id))  # FIXED: Use current_user["username"]
    conn.commit()
    conn.close()
    return {"status": "ok", "subtitle_id": subtitle_id}