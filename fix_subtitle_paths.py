

import sqlite3
import os

# --- Configuration ---
# Ensure this path points to your actual database file.
# If you are running this script from the root of the project, this should be correct.
DATABASE_PATH = os.getenv("DATABASE_PATH", "database.db")

def fix_paths(db_path):
    """
    Connects to the SQLite database and removes the 'static/' prefix
    from the file_path column in the 'subtitles' and 'episode_subtitles' tables.
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at '{db_path}'")
        return

    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    updated_movie_subs = 0
    updated_episode_subs = 0

    try:
        # --- Fix 'subtitles' table for movies ---
        print("Checking 'subtitles' table for movie subtitles...")
        # The WHERE clause ensures we only update rows that need fixing.
        cursor.execute("""
            UPDATE subtitles
            SET file_path = REPLACE(file_path, 'static/', '')
            WHERE file_path LIKE 'static/%'
        """)
        updated_movie_subs = cursor.rowcount
        print(f"Updated {updated_movie_subs} rows in 'subtitles' table.")

        # --- Fix 'episode_subtitles' table for episodes ---
        print("Checking 'episode_subtitles' table for episode subtitles...")
        cursor.execute("""
            UPDATE episode_subtitles
            SET file_path = REPLACE(file_path, 'static/', '')
            WHERE file_path LIKE 'static/%'
        """)
        updated_episode_subs = cursor.rowcount
        print(f"Updated {updated_episode_subs} rows in 'episode_subtitles' table.")

        # --- Commit the changes ---
        conn.commit()
        print("\nDatabase changes have been committed.")

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        print("Rolling back changes.")
        conn.rollback()
    finally:
        conn.close()
        print("Database connection closed.")
        
    total_updated = updated_movie_subs + updated_episode_subs
    if total_updated > 0:
        print(f"\nSuccessfully migrated {total_updated} subtitle paths.")
    else:
        print("\nNo subtitle paths needed fixing.")

if __name__ == "__main__":
    # In the Docker environment, the database is at /data/lantern.db
    # When running locally for development, it might be at the root.
    # We'll check for the docker path first.
    docker_db_path = "/data/lantern.db"
    local_db_path = "lantern.db" 

    if os.path.exists(docker_db_path):
        fix_paths(docker_db_path)
    elif os.path.exists(local_db_path):
        fix_paths(local_db_path)
    else:
        print(f"Could not find a database file at '{local_db_path}' or '{docker_db_path}'.")
        print("If you are using Docker, you should run this script inside the container, e.g.:")
        print("docker-compose exec media-server python fix_subtitle_paths.py")


