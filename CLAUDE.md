# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a single-file Python script that exports Spotify playlists and liked songs to backup formats (tab-separated text or JSON). The script uses the Spotify Web API with OAuth authentication via a local HTTP server.

## Common Commands

Set up virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Run the script with automatic timestamped filename:
```bash
python3 spotify-backup.py
# Creates: playlists-20250611-143022.txt
```

Export to JSON format with automatic filename:
```bash
python3 spotify-backup.py --format=json
# Creates: playlists-20250611-143022.json
```

Run the script with custom filename:
```bash
python3 spotify-backup.py my-playlists.txt
```

Include both playlists and liked songs:
```bash
python3 spotify-backup.py --dump=liked,playlists
```

Export your top artists and tracks:
```bash
python3 spotify-backup.py --dump=top
```

Export top tracks only from the last 4 weeks:
```bash
python3 spotify-backup.py --dump=top --top-type=tracks --time-range=short_term
```

Export everything (playlists, liked songs, and top items):
```bash
python3 spotify-backup.py --dump=playlists,liked,top
```

Use a pre-generated OAuth token (bypasses browser authorization):
```bash
python3 spotify-backup.py --token=YOUR_OAUTH_TOKEN
```

## Architecture

- **Single-file architecture**: All functionality is contained in `spotify-backup.py`
- **SpotifyAPI class**: Handles OAuth authentication, API requests, and pagination
- **OAuth flow**: Uses a local HTTP server on port 43019 to receive the authorization callback
- **Output formats**: Supports tab-separated text (default) and JSON formats
- **API endpoints used**:
  - `me` - Get user info
  - `me/tracks` - Get liked songs
  - `me/albums` - Get liked albums  
  - `users/{user_id}/playlists` - Get user playlists
  - `me/top/artists` - Get user's top artists
  - `me/top/tracks` - Get user's top tracks
  - Individual playlist track endpoints for each playlist

## Key Implementation Details

- **Dependencies**: Uses Python's built-in libraries only; Rich library is optional for enhanced UI
- **Concurrency**: Playlists are loaded concurrently using ThreadPoolExecutor (max 5 workers)
- **Progress tracking**: Rich progress bars show real-time loading status
- **Error handling**: Comprehensive error handling for HTTP errors, network issues, and JSON parsing
- **API optimization**: Uses maximum allowed batch sizes (100 for playlists, 50 for tracks/albums)
- **Automatic pagination**: Handles large playlists via the `list()` method with progress updates
- **Rate limiting**: Respects API rate limits with exponential backoff retry logic
- **Security**: Access tokens are not logged to prevent credential exposure
- **Client ID**: Hardcoded (`5c098bcc800e45d49e476265bc9b6934`) for the registered Spotify app
- **OAuth scopes**: Dynamically determined based on data being exported:
  - `playlist-read-private playlist-read-collaborative user-library-read` for playlists and liked items
  - `user-top-read` for top artists and tracks