import os
from database import initialize_db, get_db_connection
from contextlib import closing

# Create the directory for the database if it doesn't exist
db_path = os.environ.get("DATABASE_PATH", "data/lantern.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)

print("Initializing database...")
# Use a try-finally block to ensure the connection is closed
try:
    with closing(get_db_connection()) as conn:
        initialize_db()
finally:
    print("Database initialization complete.")
