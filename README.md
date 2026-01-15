# Playa Please

A personal YouTube Music alternative that generates better, more varied playlists from your liked songs and library.

## Why?

YouTube Music's "Supermix" tends to repeat the same songs too often. Playa Please syncs your YouTube Music library and generates continuous playlists with better variety using configurable diversity constraints.

## Features

- **Google OAuth Login** - Connects to your YouTube account to access your music library
- **Library Sync** - Imports your liked videos and playlists from YouTube Music
- **Smart Playlist Generation** - Algorithm that balances:
  - Artist diversity (no same artist within N songs)
  - Genre balance (no genre exceeds X% of recent plays)
  - Discovery ratio (mix of familiar favorites and rediscoveries)
  - Feedback integration (liked songs boosted, disliked excluded)
- **Web Player** - Clean interface with playback controls, queue view, and like/dislike buttons
- **Auto-skip** - Automatically skips unavailable videos and tracks them to avoid retrying

## Tech Stack

**Backend:**
- FastAPI (Python)
- SQLAlchemy + SQLite
- YouTube Data API v3 (library sync)
- ytmusicapi (search/metadata)
- yt-dlp (audio streaming)

**Frontend:**
- React + TypeScript
- Vite
- Tailwind CSS
- Howler.js (audio playback)

## Setup

### 1. Google Cloud Console

1. Create a project at [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the **YouTube Data API v3**
3. Create **OAuth 2.0 credentials** (Web application type)
4. Add authorized redirect URI: `{YOUR_URL}/auth/callback`
5. Add yourself as a test user in the OAuth consent screen (if not published)

### 2. Backend Configuration

```bash
cd backend
cp .env.example .env
# Edit .env with your Google OAuth credentials
```

Required environment variables:
- `GOOGLE_CLIENT_ID` - From Google Cloud Console
- `GOOGLE_CLIENT_SECRET` - From Google Cloud Console
- `FRONTEND_URL` - Your frontend URL
- `BACKEND_URL` - Your backend URL
- `JWT_SECRET` - Random secret string for session tokens

### 3. Install Dependencies

**Backend:**
```bash
cd backend
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
npm run build
```

### 4. Run

```bash
# From project root
./start.sh
```

Or manually:
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The app serves both the API and the built frontend static files.

## Algorithm Settings

Configurable in `.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `QUEUE_PREFETCH_SIZE` | 20 | Songs to generate per batch |
| `MIN_ARTIST_GAP` | 5 | Minimum songs between same artist |
| `MAX_GENRE_RATIO` | 0.4 | Max percentage of one genre in recent plays |
| `DISCOVERY_RATIO` | 0.3 | Percentage of "discovery" songs (not played in 30+ days) |
| `STREAM_CACHE_HOURS` | 2 | How long to cache stream URLs |

## Usage

1. Open the app and click "Sign in with Google"
2. Authorize access to your YouTube account
3. Click "Sync Library" to import your liked songs
4. Music starts playing automatically from your generated playlist
5. Use like/dislike buttons to train the algorithm

## License

MIT
