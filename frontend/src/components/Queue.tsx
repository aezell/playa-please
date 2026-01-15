import { Music } from 'lucide-react';
import type { Song } from '../api/types';

interface QueueProps {
  queue: Song[];
  currentSong: Song | null;
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function Queue({ queue, currentSong }: QueueProps) {
  // Show up to 10 songs
  const displayQueue = queue.slice(0, 10);

  return (
    <div className="bg-gray-800/30 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
        Up Next
      </h3>

      {displayQueue.length === 0 ? (
        <div className="text-center py-8">
          <Music className="w-8 h-8 text-gray-600 mx-auto mb-2" />
          <p className="text-gray-500 text-sm">Queue is empty</p>
        </div>
      ) : (
        <div className="space-y-2">
          {displayQueue.map((song, index) => {
            const isCurrent = currentSong?.video_id === song.video_id;

            return (
              <div
                key={`${song.video_id}-${index}`}
                className={`flex items-center gap-3 p-2 rounded-lg transition-colors ${
                  isCurrent
                    ? 'bg-primary-500/10 border border-primary-500/30'
                    : 'hover:bg-gray-700/50'
                }`}
              >
                {/* Thumbnail */}
                <div className="w-12 h-12 rounded overflow-hidden flex-shrink-0 bg-gray-700">
                  <img
                    src={song.thumbnail_url}
                    alt=""
                    className="w-full h-full object-cover"
                  />
                </div>

                {/* Song Info */}
                <div className="flex-1 min-w-0">
                  <p
                    className={`text-sm font-medium truncate ${
                      isCurrent ? 'text-primary-400' : 'text-white'
                    }`}
                  >
                    {song.title}
                  </p>
                  <p className="text-xs text-gray-400 truncate">{song.artist}</p>
                </div>

                {/* Duration */}
                <span className="text-xs text-gray-500 flex-shrink-0">
                  {formatDuration(song.duration_seconds)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {queue.length > 10 && (
        <p className="text-xs text-gray-500 text-center mt-4">
          +{queue.length - 10} more songs
        </p>
      )}
    </div>
  );
}
