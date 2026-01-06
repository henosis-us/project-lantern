# Lantern
Lantern is a distributed open video-serving platform featuring a central identity service, a media server for content management and streaming, and a web-based frontend for user interaction. It enables secure remote access via a public-link gateway. The backend is built with FastAPI and SQLite/PostgreSQL, while the frontend uses React and JSX for a responsive user interface.

For the fastest local setup on Windows, see: **`DEV_SETUP.md`**.

## Project Overview
- **Backend Components**:
  - **Media Server**: Handles media library scanning, streaming (HLS and direct play), subtitle management, watch history, and API endpoints.
  - **Identity Service**: Manages user authentication, JWT tokens, server claiming, and sharing permissions using PostgreSQL.
- **Frontend**: A React-based web application providing intuitive interfaces for login, library browsing, media playback, and settings.

This project supports self-hosting, with integrations to external services like TMDb for metadata and OpenSubtitles for subtitles.

## Features
### Current Features
- **Media Library Scanning**: Automatically scans configured directories for movies and TV shows, enriches metadata from TMDb, and updates the database.
- **Streaming and Playback**: Supports HLS-based streaming with FFmpeg transcoding, direct playback for compatible files, resume functionality, and progress tracking.
- **Subtitle Management**: Searches, downloads, and caches subtitles from OpenSubtitles, with user preferences and integration in playback.
- **Watch History**: Saves and retrieves user progress for movies and episodes, including a "Continue Watching" list.
- **User Authentication**: JWT-based login, registration, and role-based access (e.g., owner/admin) handled by the central Identity Service.
- **API Endpoints**: Comprehensive RESTful API for media management, streaming, history, subtitles, and more, with CORS support.
- **Error Handling and Diagnostics**: Includes logging, rate limiting, and database schema management.
- **Frontend UI**: Interactive web interface for browsing libraries, playing media with HLS support, managing subtitles, claiming servers, and handling authentication flows.

### Upcoming Features
Lantern is actively evolving to enhance functionality and close gaps with competitors. Planned features include:
- **Remote Access Integration**: Improved support for secure remote access, including NAT traversal and reverse proxy configurations.
- **Chromecast Casting**: Backend and frontend support for casting to Chromecast devices.
- **Library Sharing**: Enhanced user system with granular sharing options, PINs, and parental controls.
- **Pre-Transcode Options**: User-configurable transcoding settings for media files, with options for storage and playback.
- **Skip Intro Detection**: Automatic intro-skipping using FFmpeg or database-stored timestamps.
- **Dynamic Bandwidth Adaptation**: Automatic adjustment of streaming quality based on network conditions.
- **Offline Sync for Mobile**: Endpoints for generating download links (deferred for future mobile app integration).
- **Real-Time Transcoding Dashboard**: API for monitoring transcoding status, bandwidth, and active streams.

## Configuration
- **Database**:
  - Media Server: Uses SQLite by default (`lantern.db`). Initialize or migrate with `python database.py`.
  - Identity Service: Uses PostgreSQL; configure via `.env` file with `DATABASE_URL`, `JWT_SECRET_KEY`, etc.
- **Library Scanning**: Set scan roots in `.env` or via API. Trigger scans using `/library/scan`.
- **Environment Variables**: Use `.env` files for both media server and identity service to set API keys, ports, and secrets.
- **Frontend**: Configured via React context; handles dynamic API instances based on user authentication and server selection.

## Usage
- **Running the Services**:
  - **Media Server**: Run with `uvicorn main:app` or similar, listens on port 8000 by default.
  - **Identity Service**: Run with `uvicorn main:app`, listens on port 8001.
  - **Frontend**: Serve the React app (e.g., using `npm start` in lantern-ui directory).
- **API Endpoints** (Media Server):
  - `/library/movies`: List movies.
  - `/library/series`: List TV series.
  - `/stream/{id}`: Stream media (HLS or direct).
  - `/history/*`: Manage watch history.
  - `/subtitles/*`: Handle subtitle operations.
- **Authentication**: Use JWT tokens for protected routes. Register via Identity Service `/auth/register`.
- **Frontend Access**: Navigate through pages like Library, Login, and Playback for a seamless user experience.

## Development
- **Backend**:
  - **Dependencies**:
    - Media Server: `project-lantern/requirements.txt`
    - Identity Service: `project-lantern/identity-service/requirements.txt`
    - Install with `pip install -r <requirements.txt>` in each service folder.
  - **Running Tests**: Use Python's unittest (e.g., `python scanner.py --test`).
  - **Logging**: Configure `LOG_LEVEL` in `.env` for debug output.
- **Frontend**:
  - **Dependencies**: Managed via `npm` or `yarn`. Install with `npm install`.
  - **Development Server**: Run with `npm start` to launch the React dev server.
  - **Testing**: Use React testing libraries for component tests.
- **Cross-Component Development**: Ensure API compatibility between backend and frontend. Use tools like Swagger UI (`/docs`) for backend API testing.
- **Building and Deployment**: Backend can be containerized with Docker; frontend can be built with `npm run build` for static serving.

## License
MIT License
