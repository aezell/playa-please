/**
 * API Client for Playa Please backend
 */

import type {
  AuthStatus,
  QueueResponse,
  StreamResponse,
  FeedbackResponse,
  LibraryStats,
  SyncStatus,
  Song,
} from './types';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const message = await response.text().catch(() => 'Unknown error');
    throw new ApiError(response.status, message);
  }
  return response.json();
}

// === Auth Endpoints ===

export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await fetch('/auth/me', {
    credentials: 'include',
  });
  return handleResponse<AuthStatus>(response);
}

export function login(): void {
  // Redirect to OAuth login endpoint
  window.location.href = '/auth/login';
}

export async function logout(): Promise<void> {
  const response = await fetch('/auth/logout', {
    method: 'POST',
    credentials: 'include',
  });
  if (!response.ok) {
    throw new ApiError(response.status, 'Failed to logout');
  }
}

// === Queue Endpoints ===

export async function getQueue(): Promise<QueueResponse> {
  const response = await fetch('/api/queue', {
    credentials: 'include',
  });
  return handleResponse<QueueResponse>(response);
}

export async function nextSong(): Promise<Song | null> {
  const response = await fetch('/api/queue/next', {
    method: 'POST',
    credentials: 'include',
  });
  const data = await handleResponse<{ song?: Song }>(response);
  return data.song ?? null;
}

// === Stream Endpoints ===

export async function getStreamUrl(videoId: string): Promise<StreamResponse> {
  const response = await fetch(`/api/stream/${encodeURIComponent(videoId)}`, {
    credentials: 'include',
  });
  return handleResponse<StreamResponse>(response);
}

// === Feedback Endpoints ===

export async function likeSong(videoId: string): Promise<FeedbackResponse> {
  const response = await fetch('/api/feedback', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({
      video_id: videoId,
      feedback: 'like',
    }),
  });
  return handleResponse<FeedbackResponse>(response);
}

export async function dislikeSong(videoId: string): Promise<FeedbackResponse> {
  const response = await fetch('/api/feedback', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({
      video_id: videoId,
      feedback: 'dislike',
    }),
  });
  return handleResponse<FeedbackResponse>(response);
}

// === Library Endpoints ===

export async function syncLibrary(): Promise<SyncStatus> {
  const response = await fetch('/api/library/sync', {
    method: 'POST',
    credentials: 'include',
  });
  return handleResponse<SyncStatus>(response);
}

export async function getLibraryStats(): Promise<LibraryStats> {
  const response = await fetch('/api/library/stats', {
    credentials: 'include',
  });
  return handleResponse<LibraryStats>(response);
}

// === Audio Streaming Endpoints ===

export interface AudioStatus {
  browser_running: boolean;
  browser_authenticated: boolean;
  stream_running: boolean;
  active_listeners: number;
}

export interface NowPlayingResponse {
  video_id: string | null;
  title: string | null;
  artist: string | null;
  thumbnail: string | null;
  duration_seconds: number;
  position_seconds: number;
  state: 'idle' | 'playing' | 'paused' | 'loading' | 'error';
}

export interface ControlResponse {
  success: boolean;
  message: string;
  now_playing: NowPlayingResponse | null;
}

export async function getAudioStatus(): Promise<AudioStatus> {
  const response = await fetch('/api/audio/status', {
    credentials: 'include',
  });
  return handleResponse<AudioStatus>(response);
}

export async function getNowPlaying(): Promise<NowPlayingResponse> {
  const response = await fetch('/api/audio/now-playing', {
    credentials: 'include',
  });
  return handleResponse<NowPlayingResponse>(response);
}

export async function controlAudio(action: 'play' | 'pause' | 'skip'): Promise<ControlResponse> {
  const response = await fetch('/api/audio/control', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({ action }),
  });
  return handleResponse<ControlResponse>(response);
}

export async function playSpecificSong(videoId: string): Promise<ControlResponse> {
  const response = await fetch(`/api/audio/play/${encodeURIComponent(videoId)}`, {
    method: 'POST',
    credentials: 'include',
  });
  return handleResponse<ControlResponse>(response);
}

export { ApiError };
