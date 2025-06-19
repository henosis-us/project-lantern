#!/usr/bin/env python3
"""
investigate_tv_db.py ─ quick diagnostics for Lantern’s TV-show tables
─────────────────────────────────────────────────────────────────────
Shows what the scanner wrote to lantern.db so you can verify that it
matches the files you actually have.

USAGE
  python investigate_tv_db.py list-series
  python investigate_tv_db.py show           <series_id> [--season N]
  python investigate_tv_db.py extras
  python investigate_tv_db.py missing-runtime
  python investigate_tv_db.py raw-sql        "SELECT …"
  python investigate_tv_db.py stats
  python investigate_tv_db.py episodes       [--like TEXT]
  python investigate_tv_db.py orphans
  python investigate_tv_db.py missing-metadata [--log-file PATH]
  python investigate_tv_db.py episode-details <episode_id>

The script only needs the standard library.
"""

import argparse
import itertools
import os
import sqlite3
import sys
from textwrap import shorten

DB_PATH = os.getenv("LANTERN_DB", "lantern.db")


def connect(db_path=DB_PATH):
    if not os.path.exists(db_path):
        sys.exit(f"ERROR: cannot find SQLite file at {db_path!r}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ───────────────────────── table helpers ──────────────────────────
def tabulate(rows, cols, output_file=sys.stdout):
    """Minimal replacement for `tabulate` – formats a list[Row] nicely."""
    if not rows:
        print("(no rows)", file=output_file)
        return
    col_widths = [max(len(str(c)), max(len(str(r[c])) for r in rows)) for c in cols]
    line = "  ".join(f"{c:<{w}}" for c, w in zip(cols, col_widths))
    print(line, file=output_file)
    print("-" * len(line), file=output_file)
    for r in rows:
        print("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, col_widths)), file=output_file)
    print(file=output_file)


# ────────────────────────── commands ──────────────────────────────
def list_series(args):
    with connect() as db:
        rows = db.execute(
            "SELECT id, title, tmdb_id, first_air_date "
            "FROM   series ORDER BY title"
        ).fetchall()
    tabulate(rows, ("id", "title", "tmdb_id", "first_air_date"))


def show_series(args):
    with connect() as db:
        show = db.execute(
            "SELECT title FROM series WHERE id=?", (args.series_id,)
        ).fetchone()
        if not show:
            sys.exit("Series not found.")
        print(f"\n{show['title']} (id={args.series_id})\n")
        q = (
            "SELECT season, episode, "
            "       coalesce(title,'–')  AS ep_title, "
            "       extra_type, "
            "       duration_seconds, "
            "       filepath "
            "FROM episodes WHERE series_id=? "
        )
        params = [args.series_id]
        if args.season is not None:
            q += "AND season=? "
            params.append(args.season)
        q += "ORDER BY season, episode"
        rows = db.execute(q, params).fetchall()

    # Convert rows to dicts for potential mutability if needed
    rows = [dict(row) for row in rows]
    tabulate(
        rows,
        ("season", "episode", "ep_title", "extra_type", "duration_seconds", "filepath"),
    )


def extras(args):
    with connect() as db:
        rows = db.execute(
            "SELECT s.title         AS series, "
            "       e.season, e.episode, "
            "       e.extra_type, "
            "       e.filepath "
            "FROM   episodes e "
            "JOIN   series   s ON s.id = e.series_id "
            "WHERE  e.extra_type IS NOT NULL "
            "ORDER  BY series, season, episode"
        ).fetchall()
    # Convert rows to dicts and shorten paths
    rows = [dict(row) for row in rows]
    for r in rows:
        r["filepath"] = shorten(r["filepath"], width=60, placeholder="…")
    tabulate(rows, ("series", "season", "episode", "extra_type", "filepath"))


def missing_runtime(args):
    with connect() as db:
        rows = db.execute(
            "SELECT s.title AS series, "
            "       e.season, e.episode, "
            "       e.filepath "
            "FROM   episodes e JOIN series s ON s.id=e.series_id "
            "WHERE  e.duration_seconds = 0 "
            "ORDER BY series, season, episode"
        ).fetchall()
    # Convert rows to dicts and shorten paths
    rows = [dict(row) for row in rows]
    for r in rows:
        r["filepath"] = shorten(r["filepath"], width=60, placeholder="…")
    tabulate(rows, ("series", "season", "episode", "filepath"))


def raw_sql(args):
    with connect() as db:
        rows = db.execute(args.query).fetchall()
    if rows:
        tabulate(rows, rows[0].keys())
    else:
        print("(no rows)\n")


def stats(args):
    """Show how many episodes each series contains (+ how many are extras)"""
    with connect() as db:
        rows = db.execute("""
            SELECT  s.id,
                    s.title,
                    COUNT(e.id)                     AS eps,
                    SUM(e.extra_type IS NOT NULL)   AS extras
              FROM series s
         LEFT JOIN episodes e ON e.series_id = s.id
          GROUP BY s.id
          ORDER BY s.title
        """).fetchall()
    tabulate(rows, ("id", "title", "eps", "extras"))


def list_all_episodes(args):
    """List every episode; useful to see what series a file ended up in."""
    like = args.like
    where = ""
    params = []
    if like:
        where = "WHERE  s.title LIKE ? OR e.filepath LIKE ?"
        params = [f"%{like}%", f"%{like}%"]

    with connect() as db:
        rows = db.execute(f"""
            SELECT s.title  AS series,
                   e.season,
                   e.episode,
                   COALESCE(e.title, '–') AS ep_title,
                   e.extra_type,
                   e.filepath
              FROM episodes e
              JOIN series   s ON s.id = e.series_id
              {where}
          ORDER BY series, season, episode
        """, params).fetchall()
    # Convert rows to dicts and shorten paths
    rows = [dict(row) for row in rows]
    for r in rows:
        r["filepath"] = shorten(r["filepath"], width=60, placeholder="…")
    tabulate(rows, ("series", "season", "episode", "ep_title", "extra_type", "filepath"))


def orphans(args):
    """Episodes whose series_id has no matching row in the series table"""
    with connect() as db:
        rows = db.execute("""
            SELECT e.id,
                   e.series_id,
                   e.season,
                   e.episode,
                   e.filepath
              FROM episodes e
         LEFT JOIN series s ON s.id = e.series_id
             WHERE s.id IS NULL
          ORDER BY e.series_id, e.season, e.episode
        """).fetchall()
    # Convert rows to dicts and shorten paths
    rows = [dict(row) for row in rows]
    for r in rows:
        r["filepath"] = shorten(r["filepath"], width=60, placeholder="…")
    tabulate(rows, ("id", "series_id", "season", "episode", "filepath"))


def missing_metadata(args):
    """List series without TMDb metadata (tmdb_id IS NULL) and their episodes."""
    log_file_path = args.log_file
    if log_file_path:
        output_file = open(log_file_path, "w")
    else:
        output_file = sys.stdout

    with connect() as db:
        # Find series with no TMDb metadata (tmdb_id IS NULL)
        series_rows = db.execute("""
            SELECT id, title
              FROM series
             WHERE tmdb_id IS NULL
          ORDER BY title
        """).fetchall()

        if not series_rows:
            print("No series found without TMDb metadata.", file=output_file)
            if log_file_path:
                output_file.close()
            return

        for series in series_rows:
            series_id = series["id"]
            series_title = series["title"]
            print(f"Series ID: {series_id}, Title: '{series_title}' (no TMDb metadata)", file=output_file)

            # Fetch all episodes for this series
            episodes = db.execute("""
                SELECT filepath
                  FROM episodes
                 WHERE series_id = ?
              ORDER BY season, episode
            """, (series_id,)).fetchall()

            if not episodes:
                print("  No episodes found for this series.", file=output_file)
            else:
                print("  Episodes:", file=output_file)
                for ep in episodes:
                    print(f"    {ep['filepath']}", file=output_file)  # No truncation

            print("", file=output_file)  # Empty line for separation between series

    if log_file_path:
        output_file.close()
        print(f"Output written to {log_file_path}")


def episode_details(args):
    """Show details for a specific episode, including description metadata."""
    with connect() as db:
        row = db.execute("""
            SELECT e.id, e.series_id, s.title AS series_title, e.season, e.episode,
                   COALESCE(e.title, '–') AS ep_title,
                   COALESCE(e.overview, 'No overview') AS overview,
                   e.filepath
              FROM episodes e
              JOIN series s ON s.id = e.series_id
             WHERE e.id = ?
        """, (args.episode_id,)).fetchone()

        if not row:
            sys.exit("Episode not found.")

        # Convert to dict and shorten filepath
        row_dict = dict(row)
        row_dict["filepath"] = shorten(row_dict["filepath"], width=60, placeholder="…")

        tabulate([row_dict], ("id", "series_title", "season", "episode", "ep_title", "overview", "filepath"))


# ──────────────────────────── main ────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        prog="investigate_tv_db.py",
        description="Inspect the ‘series’ and ‘episodes’ tables inside lantern.db, including episode details.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-series", help="Show every series the scanner created")

    p_show = sub.add_parser("show", help="List episodes for a single series")
    p_show.add_argument("series_id", type=int, help="ID from list-series")
    p_show.add_argument("--season", type=int, help="Limit to one season")

    sub.add_parser("extras", help="Episodes flagged as extras/featurettes/…")

    sub.add_parser("missing-runtime", help="Episodes with duration_seconds == 0")

    p_sql = sub.add_parser("raw-sql", help="Run an arbitrary SQL query")
    p_sql.add_argument("query", help='SQL string, e.g. "SELECT count(*) FROM episodes"')

    # ── NEW AND EXISTING SUBCOMMANDS ─────────────────────────────────────────
    sub.add_parser("stats",
                   help="One line per series with count(episodes) / count(extras)")

    p_eps = sub.add_parser("episodes",
                           help="List all episodes together with the series title")
    p_eps.add_argument("--like",
                       metavar="TEXT",
                       help="SQL LIKE filter (matches series title or filepath)",
                       default=None)

    sub.add_parser("orphans",
                   help="Episodes whose series_id no longer exists")

    p_meta = sub.add_parser("missing-metadata",
                            help="List series without TMDb metadata and their episodes")
    p_meta.add_argument("--log-file", help="Path to log file for output", default=None)

    p_episode = sub.add_parser("episode-details",
                               help="Show details for a specific episode, including description metadata")
    p_episode.add_argument("episode_id", type=int, help="ID of the episode to display details for")

    args = ap.parse_args()

    match args.cmd:
        case "list-series":
            list_series(args)
        case "show":
            show_series(args)
        case "extras":
            extras(args)
        case "missing-runtime":
            missing_runtime(args)
        case "raw-sql":
            raw_sql(args)
        case "stats":
            stats(args)
        case "episodes":
            list_all_episodes(args)
        case "orphans":
            orphans(args)
        case "missing-metadata":
            missing_metadata(args)
        case "episode-details":
            episode_details(args)


if __name__ == "__main__":
    main()