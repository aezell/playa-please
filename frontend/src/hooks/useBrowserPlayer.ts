import { useState, useEffect, useRef, useCallback } from 'react';
import {
  getAudioStatus,
  getNowPlaying,
  controlAudio,
  type NowPlayingResponse,
} from '../api/client';

interface PlayerState {
  currentSong: NowPlayingResponse | null;
  isPlaying: boolean;
  progress: number;
  duration: number;
  isLoading: boolean;
  isConnected: boolean;
  browserAuthenticated: boolean;
}

interface UseBrowserPlayerReturn extends PlayerState {
  play: () => Promise<void>;
  pause: () => Promise<void>;
  skip: () => Promise<void>;
  volume: number;
  setVolume: (volume: number) => void;
  audioRef: React.RefObject<HTMLAudioElement>;
}

export function useBrowserPlayer(): UseBrowserPlayerReturn {
  const [state, setState] = useState<PlayerState>({
    currentSong: null,
    isPlaying: false,
    progress: 0,
    duration: 0,
    isLoading: true,
    isConnected: false,
    browserAuthenticated: false,
  });

  const [volume, setVolumeState] = useState(0.8);
  const audioRef = useRef<HTMLAudioElement>(null);
  const pollIntervalRef = useRef<number | null>(null);

  // Poll for now playing info
  const pollNowPlaying = useCallback(async () => {
    try {
      const nowPlaying = await getNowPlaying();
      setState(prev => ({
        ...prev,
        currentSong: nowPlaying,
        progress: nowPlaying.position_seconds,
        duration: nowPlaying.duration_seconds,
        isPlaying: nowPlaying.state === 'playing',
        isLoading: nowPlaying.state === 'loading',
      }));
    } catch (error) {
      console.error('Failed to poll now playing:', error);
    }
  }, []);

  // Check audio system status
  const checkStatus = useCallback(async () => {
    try {
      const status = await getAudioStatus();
      setState(prev => ({
        ...prev,
        isConnected: status.stream_running,
        browserAuthenticated: status.browser_authenticated,
        isLoading: false,
      }));
      return status;
    } catch (error) {
      console.error('Failed to get audio status:', error);
      setState(prev => ({ ...prev, isLoading: false }));
      return null;
    }
  }, []);

  // Initialize and continuously poll status
  useEffect(() => {
    let mounted = true;
    let statusIntervalRef: number | null = null;

    async function init() {
      await checkStatus();

      if (!mounted) return;

      // Always start polling for now playing and status updates
      pollIntervalRef.current = window.setInterval(pollNowPlaying, 1000);

      // Also poll status every 5 seconds to catch auth/connection changes
      statusIntervalRef = window.setInterval(async () => {
        if (mounted) {
          await checkStatus();
        }
      }, 5000);

      // Initial poll
      pollNowPlaying();
    }

    init();

    return () => {
      mounted = false;
      if (pollIntervalRef.current) {
        window.clearInterval(pollIntervalRef.current);
      }
      if (statusIntervalRef) {
        window.clearInterval(statusIntervalRef);
      }
    };
  }, [checkStatus, pollNowPlaying]);

  // Connect audio element to stream - always set the src
  useEffect(() => {
    if (audioRef.current) {
      // Always point to the stream URL
      if (!audioRef.current.src || !audioRef.current.src.includes('/api/audio/stream')) {
        audioRef.current.src = '/api/audio/stream';
      }
      audioRef.current.volume = volume;
    }
  }, [volume]);

  // Auto-play when isPlaying becomes true
  useEffect(() => {
    if (audioRef.current && state.isPlaying) {
      audioRef.current.play().catch(err => {
        console.log('Auto-play prevented:', err);
      });
    }
  }, [state.isPlaying]);

  // Play
  const play = useCallback(async () => {
    console.log('Play button clicked');
    try {
      setState(prev => ({ ...prev, isLoading: true }));

      // Start playing the local audio element immediately (user gesture)
      if (audioRef.current) {
        try {
          await audioRef.current.play();
          console.log('Audio element playing');
        } catch (err) {
          console.log('Audio play error:', err);
        }
      }

      // Then tell the backend to play
      const response = await controlAudio('play');
      console.log('controlAudio response:', response);

      // Update state based on response
      setState(prev => ({
        ...prev,
        currentSong: response.now_playing || prev.currentSong,
        isPlaying: true, // Optimistically set to playing
        isLoading: false,
      }));
    } catch (error) {
      console.error('Failed to play:', error);
      setState(prev => ({ ...prev, isLoading: false }));
    }
  }, []);

  // Pause
  const pause = useCallback(async () => {
    try {
      const response = await controlAudio('pause');

      // Also pause the local audio element
      if (audioRef.current) {
        audioRef.current.pause();
      }

      if (response.now_playing) {
        setState(prev => ({
          ...prev,
          currentSong: response.now_playing,
          isPlaying: false,
        }));
      }
    } catch (error) {
      console.error('Failed to pause:', error);
    }
  }, []);

  // Skip
  const skip = useCallback(async () => {
    try {
      setState(prev => ({ ...prev, isLoading: true }));
      const response = await controlAudio('skip');

      if (response.now_playing) {
        setState(prev => ({
          ...prev,
          currentSong: response.now_playing,
          isPlaying: response.now_playing?.state === 'playing',
          isLoading: false,
        }));
      }
    } catch (error) {
      console.error('Failed to skip:', error);
      setState(prev => ({ ...prev, isLoading: false }));
    }
  }, []);

  // Volume
  const setVolume = useCallback((newVolume: number) => {
    setVolumeState(newVolume);
    if (audioRef.current) {
      audioRef.current.volume = newVolume;
    }
  }, []);

  return {
    ...state,
    play,
    pause,
    skip,
    volume,
    setVolume,
    audioRef,
  };
}
