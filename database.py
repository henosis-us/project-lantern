import sqlite3
import os
from pathlib import Path

DATABASE_NAME = "lantern.db"

def get_db_connection():
    """Establishes a connection to the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    """
    Creates the necessary tables if they don't exist and makes sure
    any new columns that later versions need are added.
    """
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
        ("duration_seconds", "INTEGER DEFAULT 0"),
        ("parent_id",        "INTEGER"),
        ("vote_average",     "REAL DEFAULT 0"),
        ("genres",           "TEXT"),
        ("video_codec",      "TEXT"),
        ("audio_codec",      "TEXT"),
        ("is_direct_play",   "INTEGER DEFAULT 0")
    ):
        try:
            cursor.execute(f"ALTER TABLE movies ADD COLUMN {col} {ddl}")
            print(f"Added '{col}' column to movies table.")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL,
            password_hash TEXT       NOT NULL,
            is_admin     INTEGER     DEFAULT 0,
            created_at   TEXT        DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Watch history table for movies
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_history (
            user_id          INTEGER NOT NULL,
            movie_id         INTEGER NOT NULL,
            position_seconds INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            updated_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, movie_id),
            FOREIGN KEY (user_id)  REFERENCES users(id)   ON DELETE CASCADE,
            FOREIGN KEY (movie_id) REFERENCES movies(id)  ON DELETE CASCADE
        )
    """)

    # Watch history table for episodes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_history_ep (
            user_id          INTEGER NOT NULL,
            episode_id       INTEGER NOT NULL,
            position_seconds INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            updated_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, episode_id),
            FOREIGN KEY (user_id)   REFERENCES users(id)     ON DELETE CASCADE,
            FOREIGN KEY (episode_id)REFERENCES episodes(id)  ON DELETE CASCADE
        )
    """)

    # Subtitles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subtitles (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            movie_id      INTEGER NOT NULL,
            lang          TEXT,
            provider      TEXT,
            provider_id   TEXT,
            file_path     TEXT,
            downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(movie_id, provider, provider_id),
            FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
        )
    """)

    # Add missing columns for subtitles table
    for col, ddl in (("file_name", "TEXT"),):
        try:
            cursor.execute(f"ALTER TABLE subtitles ADD COLUMN {col} {ddl}")
            print(f"Added '{col}' column to subtitles table.")
        except sqlite3.OperationalError:
            pass  # Column already exists or table doesn't have it yet

    # Subtitle preference table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subtitle_prefs (
            user_id     INTEGER NOT NULL,
            movie_id    INTEGER NOT NULL,
            subtitle_id INTEGER,
            PRIMARY KEY (user_id, movie_id),
            FOREIGN KEY (user_id)     REFERENCES users(id)      ON DELETE CASCADE,
            FOREIGN KEY (movie_id)    REFERENCES movies(id)     ON DELETE CASCADE,
            FOREIGN KEY (subtitle_id) REFERENCES subtitles(id)  ON DELETE SET NULL
        )
    """)

    # Series table for TV shows
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT    NOT NULL,
            tmdb_id         INTEGER,
            overview        TEXT,
            poster_path     TEXT,
            first_air_date  TEXT,
            CONSTRAINT unique_title UNIQUE (title)
        )
    """)

    # Episodes table for TV episodes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id        INTEGER NOT NULL,
            season           INTEGER NOT NULL,
            episode          INTEGER NOT NULL,
            title            TEXT,
            overview         TEXT,
            filepath         TEXT    NOT NULL UNIQUE,
            duration_seconds INTEGER DEFAULT 0,
            air_date         TEXT,
            extra_type       TEXT,
            still_path       TEXT,  -- NEW: Path to the still image/thumbnail
            FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE
        )
    """)

    # Add missing columns for episodes table
    for col, ddl in (
        ("overview", "TEXT"),
        ("still_path", "TEXT")
    ):
        try:
            cursor.execute(f"ALTER TABLE episodes ADD COLUMN {col} {ddl}")
            print(f"Added '{col}' column to episodes table.")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # --- START: Added code for episode subtitles ---
    # Episode Subtitles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episode_subtitles (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id    INTEGER NOT NULL,
            lang          TEXT,
            provider      TEXT,
            provider_id   TEXT,
            file_name     TEXT,
            file_path     TEXT,
            downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(episode_id, provider, provider_id),
            FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
        )
    """)

    # Episode Subtitle preference table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episode_subtitle_prefs (
            user_id     INTEGER NOT NULL,
            episode_id  INTEGER NOT NULL,
            subtitle_id INTEGER,
            PRIMARY KEY (user_id, episode_id),
            FOREIGN KEY (user_id)     REFERENCES users(id)         ON DELETE CASCADE,
            FOREIGN KEY (episode_id)  REFERENCES episodes(id)      ON DELETE CASCADE,
            FOREIGN KEY (subtitle_id) REFERENCES episode_subtitles(id) ON DELETE SET NULL
        )
    """)
    # --- END: Added code ---

    conn.commit()
    conn.close()
    print("Database initialized successfully.")