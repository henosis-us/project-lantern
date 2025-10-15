#!/usr/bin/env python3
"""
get_claim_token.py
Fetches the current claim token for your Lantern media-server
without touching the containers by hand.
"""

import sqlite3
import os
import sys

# Path inside the media-server container’s volume
DB_PATH = r"\\wsl$\docker-desktop-data\data\docker\volumes\lantern-data\_data\lantern.db"

# If the above WSL path doesn’t work, mount the volume once and adjust:
# docker run --rm -v lantern-data:/data alpine ls /data
# then set DB_PATH to the mounted file.

def main():
    if not os.path.isfile(DB_PATH):
        print("Database not found at:", DB_PATH)
        print("Make sure the lantern-data volume is mounted or adjust DB_PATH.")
        sys.exit(1)

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM server_config WHERE key='claim_token'")
        row = cur.fetchone()

    if row:
        print("Current claim token:", row[0])
    else:
        print("No claim token stored. Restart the media-server or run the fix script.")

if __name__ == "__main__":
    main()