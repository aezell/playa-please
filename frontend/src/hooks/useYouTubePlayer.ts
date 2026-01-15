import { useState, useEffect, useRef, useCallback } from 'react';
import { getQueue, nextSong as apiNextSong } from '../api/client';
import type { Song, QueueResponse } from '../api/types';

// YouTube IFrame API types
declare global {
  interface Window {
    YT: {
      Player: new (
        elementId: string,
        options: YTPlayerOptions
      ) => YTPlayer;
      PlayerState: {
        UNSTARTED: number;
        ENDED: number;
        PLAYING: number;
        PAUSED: number;
        BUFFERING: number;
        CUED: number;
      };
    };
    onYouTubeIframeAPIReady: () => void;
  }
}

interface YTPlayerOptions {
  height?: string | number;
  width?: string | number;
  videoId?: string;
  playerVars?: {
    autoplay?: 0 | 1;
    controls?: 0 | 1;
    disablekb?: 0 | 1;
    enablejsapi?: 0 | 1;
    modestbranding?: 0 | 1;
    rel?: 0 | 1;
    showinfo?: 0 | 1;
    origin?: string;
  };
  events?: {
    onReady?: (event: YTPlayerEvent) => void;
    onStateChange?: (event: YTStateChangeEvent) => void;
    onError?: (event: YTErrorEvent) => void;
  };
}

interface YTPlayer {
  playVideo: () => void;
  pauseVideo: () => void;
  stopVideo: () => void;
  loadVideoById: (videoId: string) => void;
  cueVideoById: (videoId: string) => void;
  seekTo: (seconds: number, allowSeekAhead?: boolean) => void;
  setVolume: (volume: number) => void;
  getVolume: () => number;
  mute: () => void;
  unMute: () => void;
  isMuted: () => boolean;
  getPlayerState: () => number;
  getCurrentTime: () => number;
  getDuration: () => number;
  getVideoData: () => { video_id: string; title: string; author: string };
  destroy: () => void;
}

interface YTPlayerEvent {
  target: YTPlayer;
}

interface YTStateChangeEvent {
  target: YTPlayer;
  data: number;
}

interface YTErrorEvent {
  target: YTPlayer;
  data: number;
}

interface PlayerState {
  currentSong: Song | null;
  isPlaying: boolean;
  progress: number;
  duration: number;
  queue: Song[];
  isLoading: boolean;
  isReady: boolean;
}

interface UseYouTubePlayerReturn extends PlayerState {
  play: () => void;
  pause: () => void;
  next: () => Promise<void>;
  seek: (time: number) => void;
  volume: number;
  setVolume: (volume: number) => void;
  playerContainerId: string;
}

// Load YouTube IFrame API
function loadYouTubeAPI(): Promise<void> {
  return new Promise((resolve) => {
    if (window.YT && window.YT.Player) {
      resolve();
      return;
    }

    // Set up callback
    window.onYouTubeIframeAPIReady = () => {
      resolve();
    };

    // Load the script
    const tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    const firstScriptTag = document.getElementsByTagName('script')[0];
    firstScriptTag.parentNode?.insertBefore(tag, firstScriptTag);
  });
}

export function useYouTubePlayer(): UseYouTubePlayerReturn {
  const [state, setState] = useState<PlayerState>({
    currentSong: null,
    isPlaying: false,
    progress: 0,
    duration: 0,
    queue: [],
    isLoading: true,
    isReady: false,
  });

  const [volume, setVolumeState] = useState(80); // YouTube uses 0-100
  const playerRef = useRef<YTPlayer | null>(null);
  const progressIntervalRef = useRef<number | null>(null);
  const nextFnRef = useRef<(retryCount?: number) => Promise<void>>(() => Promise.resolve());

  const playerContainerId = 'youtube-player';

  // Clear progress interval
  const clearProgressInterval = useCallback(() => {
    if (progressIntervalRef.current !== null) {
      window.clearInterval(progressIntervalRef.current);
      progressIntervalRef.current = null;
    }
  }, []);

  // Start progress tracking
  const startProgressTracking = useCallback(() => {
    clearProgressInterval();
    progressIntervalRef.current = window.setInterval(() => {
      if (playerRef.current) {
        try {
          const currentTime = playerRef.current.getCurrentTime();
          const duration = playerRef.current.getDuration();
          if (typeof currentTime === 'number' && typeof duration === 'number') {
            setState(prev => ({
              ...prev,
              progress: currentTime,
              duration: duration || prev.duration,
            }));
          }
        } catch (e) {
          // Player might not be ready
        }
      }
    }, 250);
  }, [clearProgressInterval]);

  // Load a song
  const loadSong = useCallback((song: Song) => {
    if (!playerRef.current) {
      console.error('Player not ready');
      return;
    }

    setState(prev => ({
      ...prev,
      currentSong: song,
      isPlaying: false,
      progress: 0,
      duration: song.duration_seconds || 0,
      isLoading: true,
    }));

    try {
      playerRef.current.loadVideoById(song.video_id);
    } catch (error) {
      console.error('Failed to load video:', error);
      setState(prev => ({ ...prev, isLoading: false }));
    }
  }, []);

  // Next song with retry logic
  const next = useCallback(async (retryCount = 0) => {
    const MAX_RETRIES = 10;

    if (retryCount >= MAX_RETRIES) {
      console.error('Max retries reached');
      setState(prev => ({
        ...prev,
        currentSong: null,
        isPlaying: false,
        isLoading: false,
      }));
      return;
    }

    try {
      const newSong = await apiNextSong();

      if (newSong) {
        setState(prev => ({
          ...prev,
          queue: prev.queue.slice(1),
        }));

        loadSong(newSong);
      } else {
        // No more songs
        if (playerRef.current) {
          playerRef.current.stopVideo();
        }
        setState(prev => ({
          ...prev,
          currentSong: null,
          isPlaying: false,
          progress: 0,
        }));
      }
    } catch (error) {
      console.error(`Failed to get next song (attempt ${retryCount + 1}):`, error);
      setTimeout(() => nextFnRef.current(retryCount + 1), 500);
    }
  }, [loadSong]);

  // Keep ref updated
  useEffect(() => {
    nextFnRef.current = next;
  }, [next]);

  // Initialize player
  useEffect(() => {
    let mounted = true;

    async function init() {
      try {
        await loadYouTubeAPI();

        if (!mounted) return;

        // Create player
        playerRef.current = new window.YT.Player(playerContainerId, {
          height: '0',
          width: '0',
          playerVars: {
            autoplay: 0,
            controls: 0,
            disablekb: 1,
            enablejsapi: 1,
            modestbranding: 1,
            rel: 0,
          },
          events: {
            onReady: (event) => {
              console.log('YouTube player ready');
              event.target.setVolume(volume);
              setState(prev => ({ ...prev, isReady: true, isLoading: false }));

              // Fetch initial queue
              getQueue().then((queueResponse: QueueResponse) => {
                if (!mounted) return;

                setState(prev => ({
                  ...prev,
                  queue: queueResponse.upcoming,
                }));

                if (queueResponse.current) {
                  loadSong(queueResponse.current);
                }
              }).catch(console.error);
            },
            onStateChange: (event) => {
              const state = event.data;

              if (state === window.YT.PlayerState.PLAYING) {
                setState(prev => ({ ...prev, isPlaying: true, isLoading: false }));
                startProgressTracking();
              } else if (state === window.YT.PlayerState.PAUSED) {
                setState(prev => ({ ...prev, isPlaying: false }));
                clearProgressInterval();
              } else if (state === window.YT.PlayerState.ENDED) {
                clearProgressInterval();
                // Auto-advance
                nextFnRef.current();
              } else if (state === window.YT.PlayerState.BUFFERING) {
                setState(prev => ({ ...prev, isLoading: true }));
              }
            },
            onError: (event) => {
              console.error('YouTube player error:', event.data);
              // Error codes: 2 = invalid video ID, 5 = HTML5 error, 100 = not found, 101/150 = not embeddable
              setState(prev => ({ ...prev, isLoading: false }));

              // Auto-skip on error
              if (event.data === 100 || event.data === 101 || event.data === 150) {
                console.log('Video not available, skipping...');
                setTimeout(() => nextFnRef.current(), 500);
              }
            },
          },
        });
      } catch (error) {
        console.error('Failed to initialize YouTube player:', error);
        if (mounted) {
          setState(prev => ({ ...prev, isLoading: false }));
        }
      }
    }

    init();

    return () => {
      mounted = false;
      clearProgressInterval();
      if (playerRef.current) {
        playerRef.current.destroy();
      }
    };
  }, []);

  // Play
  const play = useCallback(() => {
    if (playerRef.current) {
      playerRef.current.playVideo();
    }
  }, []);

  // Pause
  const pause = useCallback(() => {
    if (playerRef.current) {
      playerRef.current.pauseVideo();
    }
  }, []);

  // Seek
  const seek = useCallback((time: number) => {
    if (playerRef.current) {
      playerRef.current.seekTo(time, true);
      setState(prev => ({ ...prev, progress: time }));
    }
  }, []);

  // Volume
  const setVolume = useCallback((newVolume: number) => {
    // Convert from 0-1 to 0-100 if needed
    const ytVolume = newVolume <= 1 ? Math.round(newVolume * 100) : newVolume;
    setVolumeState(ytVolume);
    if (playerRef.current) {
      playerRef.current.setVolume(ytVolume);
    }
  }, []);

  return {
    ...state,
    play,
    pause,
    next,
    seek,
    volume: volume / 100, // Return as 0-1 for UI consistency
    setVolume,
    playerContainerId,
  };
}
