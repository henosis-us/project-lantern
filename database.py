# database.py in media-server/
import sqlite3
import os
from pathlib import Path

DATABASE_NAME = os.environ.get("DATABASE_PATH", "data/lantern.db")

def get_db_connection():
    """Establishes a connection to the database."""
    db_path = Path(DATABASE_NAME)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    """Creates the necessary tables if they don't exist and makes sure any new columns that later versions need are added."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Movies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            title            TEXT    NOT NULL,
            filepath         TEXT    NOT NULL UNIQUE,
            tmdb_id          INTEGER,
            overview         TEXT,
            poster_path      TEXT,
            release_date     TEXT,
            duration_seconds INTEGER DEFAULT 0,
            parent_id        INTEGER,
            vote_average     REAL    DEFAULT 0,
            genres           TEXT,
            video_codec      TEXT,
            audio_codec      TEXT,
            is_direct_play   INTEGER DEFAULT 0,
            FOREIGN KEY(parent_id) REFERENCES movies(id)
        )
    """)
    # Add missing columns for movies table
    for col, ddl in (
        ("duration_seconds", "INTEGER DEFAULT 0"), ("parent_id", "INTEGER"),
        ("vote_average", "REAL DEFAULT 0"), ("genres", "TEXT"),
        ("video_codec", "TEXT"), ("audio_codec", "TEXT"),
        ("is_direct_play", "INTEGER DEFAULT 0")
    ):
        try:
            cursor.execute(f"ALTER TABLE movies ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # MODIFIED: Watch history table for movies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_history (
            username         TEXT    NOT NULL,
            movie_id         INTEGER NOT NULL,
            position_seconds INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            updated_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, movie_id),
            FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
        )
    """)

    # MODIFIED: Watch history table for episodes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_history_ep (
            username         TEXT    NOT NULL,
            episode_id       INTEGER NOT NULL,
            position_seconds INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            updated_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, episode_id),
            FOREIGN KEY (episode_id)REFERENCES episodes(id) ON DELETE CASCADE
        )
    """)

    # Subtitles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subtitles (
            id            INTEGER PRIMARY KEY AUTOINCREMENT, movie_id      INTEGER NOT NULL,
            lang          TEXT, provider      TEXT, provider_id   TEXT, file_path     TEXT,
            file_name     TEXT, downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(movie_id, provider, provider_id),
            FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
        )
    """)
    # Add missing columns for subtitles table
    try:
        cursor.execute("ALTER TABLE subtitles ADD COLUMN file_name TEXT")
    except sqlite3.OperationalError:
        pass

    # MODIFIED: Subtitle preference table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subtitle_prefs (
            username    TEXT    NOT NULL,
            movie_id    INTEGER NOT NULL,
            subtitle_id INTEGER,
            PRIMARY KEY (username, movie_id),
            FOREIGN KEY (movie_id)    REFERENCES movies(id)     ON DELETE CASCADE,
            FOREIGN KEY (subtitle_id) REFERENCES subtitles(id)  ON DELETE SET NULL
        )
    """)

    # Series table for TV shows
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id              INTEGER PRIMARY KEY AUTOINCREMENT, title           TEXT    NOT NULL,
            tmdb_id         INTEGER, overview        TEXT, poster_path     TEXT,
            first_air_date  TEXT, vote_average    REAL    DEFAULT 0, genres          TEXT,
            CONSTRAINT unique_title UNIQUE (title)
        )
    """)
    # Add missing columns for series table
    for col, ddl in (("vote_average", "REAL DEFAULT 0"), ("genres", "TEXT")):
        try:
            cursor.execute(f"ALTER TABLE series ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass

    # Episodes table for TV episodes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT, series_id        INTEGER NOT NULL,
            season           INTEGER NOT NULL, episode          INTEGER NOT NULL, title            TEXT,
            overview         TEXT, filepath         TEXT    NOT NULL UNIQUE, duration_seconds INTEGER DEFAULT 0,
            air_date         TEXT, extra_type       TEXT, still_path       TEXT,
            video_codec      TEXT, audio_codec     TEXT, is_direct_play   INTEGER DEFAULT 0,
            FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE
        )
    """)
    # Add missing columns for episodes table
    for col, ddl in (
        ("overview", "TEXT"),
        ("still_path", "TEXT"),
        ("video_codec", "TEXT"),
        ("audio_codec", "TEXT"),
        ("is_direct_play", "INTEGER DEFAULT 0"),
    ):
        try:
            cursor.execute(f"ALTER TABLE episodes ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass

    # Episode Subtitles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episode_subtitles (
            id            INTEGER PRIMARY KEY AUTOINCREMENT, episode_id    INTEGER NOT NULL,
            lang          TEXT, provider      TEXT, provider_id   TEXT, file_name     TEXT,
            file_path     TEXT, downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(episode_id, provider, provider_id),
            FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
        )
    """)

    # MODIFIED: Episode Subtitle preference table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episode_subtitle_prefs (
            username    TEXT    NOT NULL,
            episode_id  INTEGER NOT NULL,
            subtitle_id INTEGER,
            PRIMARY KEY (username, episode_id),
            FOREIGN KEY (episode_id)  REFERENCES episodes(id)      ON DELETE CASCADE,
            FOREIGN KEY (subtitle_id) REFERENCES episode_subtitles(id) ON DELETE SET NULL
        )
    """)

    # NEW: Add server_config table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_config ( key TEXT PRIMARY KEY, value TEXT NOT NULL )
    """)

    # NEW: Add libraries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS libraries (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, path TEXT NOT NULL, type TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")
