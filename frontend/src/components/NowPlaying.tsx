import { useState } from 'react';
import { ThumbsUp, ThumbsDown, Music } from 'lucide-react';
import { likeSong, dislikeSong } from '../api/client';
import type { Song } from '../api/types';

interface NowPlayingProps {
  song: Song | null;
  isLoading?: boolean;
}

export function NowPlaying({ song, isLoading }: NowPlayingProps) {
  const [feedback, setFeedback] = useState<'like' | 'dislike' | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleLike = async () => {
    if (!song || isSubmitting) return;

    setIsSubmitting(true);
    try {
      await likeSong(song.video_id);
      setFeedback(feedback === 'like' ? null : 'like');
    } catch (error) {
      console.error('Failed to like song:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDislike = async () => {
    if (!song || isSubmitting) return;

    setIsSubmitting(true);
    try {
      await dislikeSong(song.video_id);
      setFeedback(feedback === 'dislike' ? null : 'dislike');
    } catch (error) {
      console.error('Failed to dislike song:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center">
        {/* Placeholder album art */}
        <div className="w-64 h-64 sm:w-72 sm:h-72 md:w-80 md:h-80 bg-gray-800 rounded-lg flex items-center justify-center animate-pulse">
          <Music className="w-16 h-16 text-gray-600" />
        </div>

        {/* Placeholder text */}
        <div className="mt-6 flex flex-col items-center gap-2">
          <div className="h-7 w-48 bg-gray-800 rounded animate-pulse" />
          <div className="h-5 w-32 bg-gray-800 rounded animate-pulse" />
        </div>
      </div>
    );
  }

  if (!song) {
    return (
      <div className="flex flex-col items-center">
        <div className="w-64 h-64 sm:w-72 sm:h-72 md:w-80 md:h-80 bg-gray-800 rounded-lg flex items-center justify-center">
          <Music className="w-16 h-16 text-gray-600" />
        </div>
        <div className="mt-6 text-center">
          <p className="text-gray-400">No song playing</p>
          <p className="text-sm text-gray-500 mt-1">Start your supermix to begin</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center">
      {/* Album Art */}
      <div className="w-64 h-64 sm:w-72 sm:h-72 md:w-80 md:h-80 rounded-lg overflow-hidden shadow-2xl shadow-black/50">
        <img
          src={song.thumbnail_url}
          alt={`${song.title} album art`}
          className="w-full h-full object-cover"
        />
      </div>

      {/* Song Info */}
      <div className="mt-6 text-center max-w-sm">
        <h2 className="text-xl sm:text-2xl font-bold text-white truncate">
          {song.title}
        </h2>
        <p className="text-gray-400 mt-1 truncate">{song.artist}</p>
        {song.album && (
          <p className="text-gray-500 text-sm mt-1 truncate">{song.album}</p>
        )}
      </div>

      {/* Like/Dislike Buttons */}
      <div className="flex items-center gap-6 mt-6">
        <button
          onClick={handleDislike}
          disabled={isSubmitting}
          className={`p-3 rounded-full transition-all ${
            feedback === 'dislike'
              ? 'bg-red-500/20 text-red-400'
              : 'text-gray-400 hover:text-white hover:bg-gray-800'
          } disabled:opacity-50`}
          title="Dislike"
        >
          <ThumbsDown className="w-6 h-6" />
        </button>

        <button
          onClick={handleLike}
          disabled={isSubmitting}
          className={`p-3 rounded-full transition-all ${
            feedback === 'like'
              ? 'bg-primary-500/20 text-primary-400'
              : 'text-gray-400 hover:text-white hover:bg-gray-800'
          } disabled:opacity-50`}
          title="Like"
        >
          <ThumbsUp className="w-6 h-6" />
        </button>
      </div>
    </div>
  );
}
