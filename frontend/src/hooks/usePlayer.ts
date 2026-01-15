import { useState, useEffect, useRef, useCallback } from 'react';
import { Howl } from 'howler';
import { getQueue, getStreamUrl, nextSong as apiNextSong } from '../api/client';
import type { Song, QueueResponse } from '../api/types';

interface PlayerState {
  currentSong: Song | null;
  isPlaying: boolean;
  progress: number;
  duration: number;
  queue: Song[];
  isLoading: boolean;
}

interface UsePlayerReturn extends PlayerState {
  play: () => void;
  pause: () => void;
  next: () => Promise<void>;
  seek: (time: number) => void;
  volume: number;
  setVolume: (volume: number) => void;
}

export function usePlayer(): UsePlayerReturn {
  const [state, setState] = useState<PlayerState>({
    currentSong: null,
    isPlaying: false,
    progress: 0,
    duration: 0,
    queue: [],
    isLoading: true,
  });

  const [volume, setVolumeState] = useState(0.8);
  const howlRef = useRef<Howl | null>(null);
  const progressIntervalRef = useRef<number | null>(null);
  const nextStreamUrlRef = useRef<string | null>(null);

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
      if (howlRef.current && howlRef.current.playing()) {
        const seek = howlRef.current.seek();
        if (typeof seek === 'number') {
          setState(prev => ({ ...prev, progress: seek }));
        }
      }
    }, 250);
  }, [clearProgressInterval]);

  // Pre-fetch next song's stream URL
  const prefetchNextSong = useCallback(async (queue: Song[]) => {
    if (queue.length > 0) {
      try {
        const streamResponse = await getStreamUrl(queue[0].video_id);
        nextStreamUrlRef.current = streamResponse.url;
      } catch (error) {
        console.error('Failed to prefetch next song:', error);
        nextStreamUrlRef.current = null;
      }
    }
  }, []);

  // Load and play a song
  const loadSong = useCallback(async (song: Song, streamUrl?: string) => {
    // Unload previous song
    if (howlRef.current) {
      howlRef.current.unload();
      howlRef.current = null;
    }
    clearProgressInterval();

    setState(prev => ({
      ...prev,
      currentSong: song,
      isPlaying: false,
      progress: 0,
      duration: song.duration_seconds,
      isLoading: true,
    }));

    try {
      // Use provided stream URL or fetch new one
      const url = streamUrl || (await getStreamUrl(song.video_id)).url;

      howlRef.current = new Howl({
        src: [url],
        html5: true,
        volume: volume,
        onload: () => {
          const duration = howlRef.current?.duration() || song.duration_seconds;
          setState(prev => ({
            ...prev,
            duration,
            isLoading: false,
          }));
        },
        onplay: () => {
          setState(prev => ({ ...prev, isPlaying: true }));
          startProgressTracking();
        },
        onpause: () => {
          setState(prev => ({ ...prev, isPlaying: false }));
          clearProgressInterval();
        },
        onstop: () => {
          setState(prev => ({ ...prev, isPlaying: false, progress: 0 }));
          clearProgressInterval();
        },
        onend: () => {
          clearProgressInterval();
          // Auto-advance to next song
          next();
        },
        onloaderror: (_, error) => {
          console.error('Failed to load audio:', error);
          setState(prev => ({ ...prev, isLoading: false }));
        },
        onplayerror: (_, error) => {
          console.error('Failed to play audio:', error);
          setState(prev => ({ ...prev, isPlaying: false }));
        },
      });

      // Start playing
      howlRef.current.play();
    } catch (error) {
      console.error('Failed to load song:', error);
      setState(prev => ({ ...prev, isLoading: false }));
      // Auto-skip unavailable songs
      console.log('Skipping unavailable song, trying next...');
      setTimeout(() => next(), 500);
    }
  }, [volume, clearProgressInterval, startProgressTracking]);

  // Next song
  const next = useCallback(async () => {
    try {
      // Call API to advance queue
      const newSong = await apiNextSong();

      if (newSong) {
        // Use prefetched URL if available
        const prefetchedUrl = nextStreamUrlRef.current;
        nextStreamUrlRef.current = null;

        // Update queue
        setState(prev => ({
          ...prev,
          queue: prev.queue.slice(1),
        }));

        // Load the new song
        await loadSong(newSong, prefetchedUrl || undefined);

        // Prefetch the next one
        setState(prev => {
          prefetchNextSong(prev.queue);
          return prev;
        });
      } else {
        // No more songs in queue
        if (howlRef.current) {
          howlRef.current.unload();
          howlRef.current = null;
        }
        setState(prev => ({
          ...prev,
          currentSong: null,
          isPlaying: false,
          progress: 0,
        }));
      }
    } catch (error) {
      console.error('Failed to skip to next song:', error);
    }
  }, [loadSong, prefetchNextSong]);

  // Initial queue fetch
  useEffect(() => {
    let mounted = true;

    async function initPlayer() {
      try {
        const queueResponse: QueueResponse = await getQueue();

        if (!mounted) return;

        setState(prev => ({
          ...prev,
          queue: queueResponse.upcoming,
          isLoading: false,
        }));

        // Load current song if available
        if (queueResponse.current) {
          await loadSong(queueResponse.current);
          // Prefetch next song
          prefetchNextSong(queueResponse.upcoming);
        }
      } catch (error) {
        console.error('Failed to initialize player:', error);
        if (mounted) {
          setState(prev => ({ ...prev, isLoading: false }));
        }
      }
    }

    initPlayer();

    return () => {
      mounted = false;
      if (howlRef.current) {
        howlRef.current.unload();
      }
      clearProgressInterval();
    };
  }, []);

  // Play
  const play = useCallback(() => {
    if (howlRef.current) {
      howlRef.current.play();
    }
  }, []);

  // Pause
  const pause = useCallback(() => {
    if (howlRef.current) {
      howlRef.current.pause();
    }
  }, []);

  // Seek
  const seek = useCallback((time: number) => {
    if (howlRef.current) {
      howlRef.current.seek(time);
      setState(prev => ({ ...prev, progress: time }));
    }
  }, []);

  // Volume
  const setVolume = useCallback((newVolume: number) => {
    setVolumeState(newVolume);
    if (howlRef.current) {
      howlRef.current.volume(newVolume);
    }
  }, []);

  return {
    ...state,
    play,
    pause,
    next,
    seek,
    volume,
    setVolume,
  };
}
