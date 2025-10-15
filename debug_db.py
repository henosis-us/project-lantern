# debug_db.py
import sqlite3

DATABASE_NAME = "lantern.db"

def check_movie_durations():
    """Connects to the DB and prints the duration for each movie."""
    print(f"--- Checking contents of {DATABASE_NAME} ---")
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT id, title, duration_seconds FROM movies ORDER BY title")
        movies = cursor.fetchall()

        if not movies:
            print("No movies found in the database.")
            return

        print(f"{'ID':<5} | {'Duration (s)':<15} | {'Title':<40}")
        print("-" * 65)
        for movie in movies:
            movie_id = movie['id']
            title = movie['title']
            duration = movie['duration_seconds']
            
            status = ""
            if duration is None or duration == 0:
                status = " <-- PROBLEM: Duration is missing or zero!"
            
            print(f"{movie_id:<5} | {str(duration):<15} | {title[:38]:<40}{status}")

        conn.close()
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    check_movie_durations()