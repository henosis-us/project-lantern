# Lantern Backend

Lantern is a self-hosted media server for streaming movies and TV shows, built with FastAPI and SQLite. It provides a RESTful API for media management, playback, and user authentication. This backend repo handles the core logic, database interactions, and integrations with external services like TMDb and OpenSubtitles.

## Features

### Current Features
- **Media Library Scanning**: Automatically index movies and TV shows from configured directories, with metadata enrichment from TMDb.
- **Streaming and Playback**: HLS-based streaming with dynamic transcoding using FFmpeg, direct play for compatible files, and resume functionality.
- **Subtitle Management**: Search, download, and cache subtitles from OpenSubtitles, with user preferences.
- **Watch History**: Save and retrieve progress for movies and TV episodes, with a "Continue Watching" list.
- **User Authentication**: JWT-based login and registration, with role-based access (e.g., owner/admin privileges).
- **API Endpoints**: Comprehensive REST API for all operations, with CORS support for frontend integration.
- **Error Handling and Diagnostics**: Robust logging, rate limiting for APIs, and schema evolution for the database.

### Upcoming Features
Lantern is evolving to close gaps with competitors like Plex. Here's a roadmap of features in development or planned:
- **Remote Access Integration**: Enable hosting alongside other services for secure remote access, with NAT traversal or reverse proxy support.
- **Chromecast Casting**: Add backend support for casting to Chromecast devices, including protocol handling.
- **Library Sharing**: Enhance the user system to support multiple users with granular sharing, PINs, and parental controls, similar to Plex.
- **Pre-Transcode Options**: Allow users to configure transcoding for all media, first-time playback only, or specific titles, with storage for pre-transcoded files.
- **Skip Intro Detection**: Implement intro-skipping by storing timestamps in the database or using FFmpeg for detection.
- **Dynamic Bandwidth Adaptation**: Automatically adjust streaming quality based on client network conditions.
- **Offline Sync for Mobile**: (Deferred) Add endpoints for generating download links, to be used by a future mobile app.
- **Real-Time Transcoding Dashboard**: API for monitoring transcoding status, bandwidth, and active streams.

## Configuration
- **Database**: Uses SQLite by default (`lantern.db`). Run `python database.py` to initialize or migrate the schema.
- **Library Scanning**: Configure scan roots in `.env` or via API. Use the `/library/scan` endpoint to trigger a scan.
- **API Documentation**: Access Swagger UI at `/docs` for interactive API testing.

## Usage
- **API Endpoints**: 
  - `/library/movies`: List all movies.
  - `/library/series`: List all TV series.
  - `/stream/{id}`: Start streaming a movie or episode (handles HLS or direct play).
  - `/history/*`: Manage watch history and progress.
  - `/subtitles/*`: Handle subtitle search, download, and selection.
- **Authentication**: Use JWT tokens for protected routes. Register users via `/auth/register`.

## Development
- **Running Tests**: Use Python's unittest for scanner tests (e.g., `python scanner.py --test`).
- **Logging**: Set `LOG_LEVEL` in `.env` for debug output.
- **Dependencies**: Managed via `requirements.txt`. Add new deps with `pip install` and update the file.


## License
MIT License