import { Play, Pause, SkipForward, Volume2 } from 'lucide-react';

interface PlayerControlsProps {
  isPlaying: boolean;
  progress: number;
  duration: number;
  volume: number;
  isLoading?: boolean;
  seekDisabled?: boolean;
  onPlay: () => void;
  onPause: () => void;
  onNext: () => void;
  onSeek: (time: number) => void;
  onVolumeChange: (volume: number) => void;
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function PlayerControls({
  isPlaying,
  progress,
  duration,
  volume,
  isLoading,
  seekDisabled,
  onPlay,
  onPause,
  onNext,
  onSeek,
  onVolumeChange,
}: PlayerControlsProps) {
  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (seekDisabled) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const percentage = clickX / rect.width;
    const newTime = percentage * duration;
    onSeek(Math.max(0, Math.min(duration, newTime)));
  };

  const handleProgressChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSeek(parseFloat(e.target.value));
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onVolumeChange(parseFloat(e.target.value));
  };

  const progressPercentage = duration > 0 ? (progress / duration) * 100 : 0;

  return (
    <div className="w-full max-w-lg mx-auto">
      {/* Progress Bar */}
      <div className="mb-4">
        <div
          className={`relative h-1 bg-gray-700 rounded-full group ${seekDisabled ? 'cursor-default' : 'cursor-pointer'}`}
          onClick={handleProgressClick}
        >
          {/* Progress fill */}
          <div
            className="absolute h-full bg-primary-500 rounded-full transition-all"
            style={{ width: `${progressPercentage}%` }}
          />
          {/* Hover handle */}
          {!seekDisabled && (
            <div
              className="absolute w-3 h-3 bg-white rounded-full -top-1 opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
              style={{ left: `calc(${progressPercentage}% - 6px)` }}
            />
          )}
        </div>

        {/* Hidden range input for accessibility */}
        <input
          type="range"
          min="0"
          max={duration || 100}
          value={progress}
          onChange={handleProgressChange}
          className="sr-only"
          aria-label="Seek"
        />

        {/* Time display */}
        <div className="flex justify-between mt-2 text-xs text-gray-400">
          <span>{formatTime(progress)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-center gap-6">
        {/* Play/Pause */}
        <button
          onClick={isPlaying ? onPause : onPlay}
          disabled={isLoading}
          className="w-14 h-14 bg-white rounded-full flex items-center justify-center text-gray-900 hover:scale-105 transition-transform disabled:opacity-50 disabled:hover:scale-100"
          aria-label={isPlaying ? 'Pause' : 'Play'}
        >
          {isLoading ? (
            <div className="w-5 h-5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
          ) : isPlaying ? (
            <Pause className="w-6 h-6" fill="currentColor" />
          ) : (
            <Play className="w-6 h-6 ml-1" fill="currentColor" />
          )}
        </button>

        {/* Skip Forward */}
        <button
          onClick={onNext}
          disabled={isLoading}
          className="p-3 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
          aria-label="Skip to next"
        >
          <SkipForward className="w-6 h-6" />
        </button>
      </div>

      {/* Volume Control */}
      <div className="flex items-center justify-center gap-3 mt-6">
        <Volume2 className="w-4 h-4 text-gray-400" />
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={volume}
          onChange={handleVolumeChange}
          className="w-24"
          aria-label="Volume"
        />
      </div>
    </div>
  );
}
