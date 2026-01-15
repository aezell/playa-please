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

export { ApiError };
