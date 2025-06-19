# history.py
from fastapi import APIRouter, Depends, Body, HTTPException, Query
from database import get_db_connection
from auth import get_current_user

router = APIRouter(prefix="/history", tags=["history"])


def _get_history_config(item_type: str):
    """Helper to get table and column names based on item_type."""
    if item_type == "movie":
        return "watch_history", "movie_id"
    elif item_type == "episode":
        return "watch_history_ep", "episode_id"
    else:
        # This case should be prevented by FastAPI's enum validation in Query
        raise HTTPException(status_code=400, detail="Invalid item_type.")

# --- MUST BE FIRST: Specific routes before dynamic ones ---

@router.get("/continue/", summary="Get a list of items to continue watching")
def continue_list(limit: int = 20, u=Depends(get_current_user)):
    """
    Gets a combined list of movies and TV episodes that are partially watched,
    ordered by the most recently watched.
    """
    conn = get_db_connection()

    # Movie continue list
    movies = conn.execute("""
        SELECT m.*, w.position_seconds
          FROM watch_history w
          JOIN movies m ON m.id = w.movie_id
         WHERE w.user_id=?
           AND w.position_seconds < m.duration_seconds * 0.90
      ORDER BY w.updated_at DESC
         LIMIT ?
    """, (u["id"], limit)).fetchall()

    # Episode continue list (now includes series poster_path)
    episodes = conn.execute("""
        SELECT e.*, 
               s.title AS series_title, 
               s.id as series_id, 
               s.poster_path as series_poster_path, 
               w.position_seconds
          FROM watch_history_ep w
          JOIN episodes e ON e.id = w.episode_id
          JOIN series   s ON s.id = e.series_id
         WHERE w.user_id=?
           AND w.position_seconds < e.duration_seconds * 0.90
      ORDER BY w.updated_at DESC
         LIMIT ?
    """, (u["id"], limit)).fetchall()

    conn.close()
    return {
        "movies": [dict(r) for r in movies],
        "episodes": [dict(r) for r in episodes]
    }

# --- Unified CRUD Endpoints for Movies and Episodes (now after /continue) ---

@router.put("/{item_id}", summary="Save watch progress for an item")
def save_progress(
        item_id: int,
        position_seconds: int = Body(..., ge=0, embed=True),
        duration_seconds: int = Body(..., ge=0, embed=True),
        item_type: str = Query(..., enum=["movie", "episode"]),
        u=Depends(get_current_user)):
    """
    Saves or updates the watch progress for a given movie or episode.
    If progress is over 90%, the item is considered "watched" and its
    history record is deleted to remove it from the 'Continue Watching' list.
    """
    table_name, id_column = _get_history_config(item_type)
    conn = get_db_connection()

    finished_cutoff = 0.90
    if duration_seconds and (position_seconds / duration_seconds) >= finished_cutoff:
        conn.execute(
            f"DELETE FROM {table_name} WHERE user_id=? AND {id_column}=?",
            (u["id"], item_id)
        )
    else:
        conn.execute(f"""
            INSERT INTO {table_name} (user_id, {id_column}, position_seconds, duration_seconds)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, {id_column})
            DO UPDATE SET position_seconds=excluded.position_seconds,
                          duration_seconds=excluded.duration_seconds,
                          updated_at=CURRENT_TIMESTAMP
        """, (u["id"], item_id, position_seconds, duration_seconds))

    conn.commit()
    conn.close()
    return {"status": "ok"}


@router.get("/{item_id}", summary="Get watch progress for an item")
def get_progress(
        item_id: int,
        item_type: str = Query(..., enum=["movie", "episode"]),
        u=Depends(get_current_user)):
    """Retrieves the last saved watch position for a movie or episode."""
    table_name, id_column = _get_history_config(item_type)
    conn = get_db_connection()

    row = conn.execute(
        f"SELECT position_seconds, duration_seconds FROM {table_name} "
        f"WHERE user_id=? AND {id_column}=?", (u["id"], item_id)
    ).fetchone()

    conn.close()
    return dict(row) if row else {}


@router.delete("/{item_id}", summary="Clear watch progress for an item")
def clear_progress(
        item_id: int,
        item_type: str = Query(..., enum=["movie", "episode"]),
        u=Depends(get_current_user)):
    """Deletes the watch history for a specific movie or episode."""
    table_name, id_column = _get_history_config(item_type)
    conn = get_db_connection()

    conn.execute(
        f"DELETE FROM {table_name} WHERE user_id=? AND {id_column}=?",
        (u["id"], item_id)
    )

    conn.commit()
    conn.close()
    return {"status": "ok"}