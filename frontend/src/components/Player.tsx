import { usePlayer } from '../hooks/usePlayer';
import { Header } from './Header';
import { NowPlaying } from './NowPlaying';
import { PlayerControls } from './PlayerControls';
import { Queue } from './Queue';
import { SyncStatus } from './SyncStatus';
import type { User } from '../api/types';

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
    queue,
    isLoading,
    play,
    pause,
    next,
    seek,
    volume,
    setVolume,
  } = usePlayer();

  return (
    <div className="min-h-screen bg-gray-900 flex flex-col">
      <Header user={user} onLogout={onLogout} />

      <main className="flex-1 flex flex-col lg:flex-row">
        {/* Main Player Area */}
        <div className="flex-1 flex flex-col items-center justify-center p-6 lg:p-12">
          <div className="w-full max-w-md">
            <NowPlaying song={currentSong} isLoading={isLoading} />

            <div className="mt-8">
              <PlayerControls
                isPlaying={isPlaying}
                progress={progress}
                duration={duration}
                volume={volume}
                isLoading={isLoading}
                onPlay={play}
                onPause={pause}
                onNext={next}
                onSeek={seek}
                onVolumeChange={setVolume}
              />
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <aside className="w-full lg:w-80 xl:w-96 bg-gray-800/20 border-t lg:border-t-0 lg:border-l border-gray-700/50 p-4 lg:p-6 space-y-6 overflow-y-auto">
          <Queue queue={queue} currentSong={currentSong} />
          <SyncStatus />
        </aside>
      </main>
    </div>
  );
}
