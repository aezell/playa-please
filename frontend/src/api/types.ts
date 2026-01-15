/**
 * Shared TypeScript types - mirrors backend schemas
 */

// === Auth Types ===

export interface User {
  id: string;
  email: string;
  name: string;
  picture?: string;
}

export interface AuthStatus {
  authenticated: boolean;
  user?: User;
}

// === Song Types ===

export interface Artist {
  id: string;
  name: string;
}

export interface Song {
  video_id: string;
  title: string;
  artist: string;
  artist_id?: string;
  album?: string;
  album_id?: string;
  duration_seconds: number;
  thumbnail_url: string;
  genres: string[];
}

export interface SongWithFeedback extends Song {
  feedback?: 'like' | 'dislike' | null;
  play_count: number;
  last_played?: string;
}

// === Player Types ===

export interface StreamResponse {
  url: string;
  expires_at: string;
}

export interface QueueResponse {
  current?: Song;
  upcoming: Song[];
  history: Song[];
}

export interface NowPlayingResponse {
  song?: Song;
  is_playing: boolean;
  progress_seconds: number;
  queue_position: number;
}

// === Feedback Types ===

export interface FeedbackRequest {
  video_id: string;
  feedback: 'like' | 'dislike';
}

export interface FeedbackResponse {
  success: boolean;
  message: string;
}

// === Library Types ===

export interface LibraryStats {
  total_songs: number;
  liked_songs: number;
  total_artists: number;
  total_genres: number;
  last_synced?: string;
}

export interface SyncStatus {
  status: 'idle' | 'syncing' | 'complete' | 'error';
  progress: number;
  message: string;
}
