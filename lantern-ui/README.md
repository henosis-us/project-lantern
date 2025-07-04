# Lantern Frontend

Lantern is a web-based frontend for a self-hosted media server, built with React and integrated with a FastAPI backend. This repo contains the user interface for browsing, searching, and playing media content. It provides a responsive, modern UI with support for movies, TV shows, and streaming controls.

## Features

### Current Features
- **Media Browsing**: Grid-based library for movies and TV shows, with search and filtering.
- **Playback Controls**: HLS streaming with resume, seek, and minimize functionality.
- **User Authentication**: Login and registration pages with JWT integration.
- **Modals and Overlays**: For movie details, TV season browsing, settings, and subtitle selection.
- **Responsive Design**: Dark-mode UI with animations, supporting desktop and mobile views.
- **Integration**: Communicates with the backend API for all data and streaming operations.

### Upcoming Features (Note: Primarily Backend-Driven)
- Features like Chromecast casting, dynamic bandwidth adaptation, and pre-transcode options will be handled by the backend and reflected here via API updates.
- **Offline Sync**: Planned for a future mobile app version.
- **UI Enhancements**: Based on backend additions, e.g., real-time transcoding dashboard or skip intro controls.

## Usage
- **Authentication**: Log in via the `/login` page to access the library.
- **Navigation**: Tabs for movies and TV shows, with search functionality.
- **Playback**: Click a movie or episode to open the player overlay with controls.
- **Settings**: Adjust playback preferences in the settings modal.

## Development
- **Dependencies**: Managed via `package.json`. Use `npm install` for new packages.
- **Routing**: Uses React Router for navigation between pages.
- **State Management**: Context API for auth and settings; hooks for HLS streaming.
- **Testing**: Add Jest or React Testing Library tests for components.
- **Deployment**: Build for production with `npm run build`, then serve the static files (e.g., via Nginx or the backend server).

## Integration with Backend
- This frontend relies on the Lantern backend API for all data.
- Key Endpoints:
  - `/auth/*`: For login and registration.
  - `/library/*`: For fetching movies and series.
  - `/stream/*`: For starting playback streams.
  - `/history/*`: For watch progress.
  - `/subtitles/*`: For subtitle management.
- Ensure CORS is enabled in the backend to allow requests from this frontend.

## Contribution Guidelines
- **Issues**: Report bugs or suggest features on GitHub.
- **Pull Requests**: Focus on UI improvements, bug fixes, or new components.
- **Code Style**: Use ESLint and Prettier for consistent formatting.

## License
MIT License (or align with backend license).