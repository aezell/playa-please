import { useBrowserPlayer } from '../hooks/useBrowserPlayer';
import { Header } from './Header';
import { NowPlaying } from './NowPlaying';
import { PlayerControls } from './PlayerControls';
import { SyncStatus } from './SyncStatus';
import type { User, Song } from '../api/types';

interface PlayerProps {
  user: User;
  onLogout: () => void;
}

export function Player({ user, onLogout }: PlayerProps) {
  const {
    currentSong,
    isPlaying,
    progress,
    duration,
    isLoading,
    isConnected,
    browserAuthenticated,
    play,
    pause,
    skip,
    volume,
    setVolume,
    audioRef,
  } = useBrowserPlayer();

  // Convert NowPlayingResponse to Song-like object for NowPlaying component
  const songForDisplay: Song | null = currentSong && currentSong.video_id ? {
    video_id: currentSong.video_id,
    title: currentSong.title || 'Unknown',
    artist: currentSong.artist || 'Unknown',
    duration_seconds: currentSong.duration_seconds,
    thumbnail_url: currentSong.thumbnail || '',
    genres: [],
  } : null;

  return (
    <div className="min-h-screen bg-gray-900 flex flex-col">
      <Header user={user} onLogout={onLogout} />

      <main className="flex-1 flex flex-col lg:flex-row">
        {/* Main Player Area */}
        <div className="flex-1 flex flex-col items-center justify-center p-6 lg:p-12">
          <div className="w-full max-w-md">
            {/* Browser Auth Status */}
            {!browserAuthenticated && (
              <div className="mb-6 p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg text-center">
                <p className="text-yellow-400 text-sm">
                  Browser not authenticated. Please wait for setup or check server logs.
                </p>
              </div>
            )}

            {!isConnected && browserAuthenticated && (
              <div className="mb-6 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg text-center">
                <p className="text-blue-400 text-sm">
                  Connecting to audio stream...
                </p>
              </div>
            )}

            <NowPlaying song={songForDisplay} isLoading={isLoading} />

            <div className="mt-8">
              <PlayerControls
                isPlaying={isPlaying}
                progress={progress}
                duration={duration}
                volume={volume}
                isLoading={isLoading}
                onPlay={play}
                onPause={pause}
                onNext={skip}
                onSeek={() => {}} // Seeking not supported in stream mode
                onVolumeChange={setVolume}
                seekDisabled={true}
              />
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <aside className="w-full lg:w-80 xl:w-96 bg-gray-800/20 border-t lg:border-t-0 lg:border-l border-gray-700/50 p-4 lg:p-6 space-y-6 overflow-y-auto">
          <SyncStatus />
        </aside>
      </main>

      {/* Hidden audio element for stream playback */}
      <audio ref={audioRef} className="hidden" />
    </div>
  );
}
