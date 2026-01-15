import { useState, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';
import { syncLibrary, getLibraryStats } from '../api/client';
import type { LibraryStats, SyncStatus as SyncStatusType } from '../api/types';

export function SyncStatus() {
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatusType | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const data = await getLibraryStats();
      setStats(data);
    } catch (error) {
      console.error('Failed to fetch library stats:', error);
    }
  };

  const handleSync = async () => {
    if (isSyncing) return;

    setIsSyncing(true);
    setSyncStatus({ status: 'syncing', progress: 0, message: 'Starting sync...' });

    try {
      const result = await syncLibrary();
      setSyncStatus(result);

      // Refetch stats after sync
      if (result.status === 'complete') {
        await fetchStats();
      }
    } catch (error) {
      console.error('Sync failed:', error);
      setSyncStatus({
        status: 'error',
        progress: 0,
        message: 'Sync failed. Please try again.',
      });
    } finally {
      setIsSyncing(false);
    }
  };

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'Never';
    const date = new Date(dateString);
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  return (
    <div className="bg-gray-800/30 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Library
        </h3>
        <button
          onClick={handleSync}
          disabled={isSyncing}
          className="flex items-center gap-2 px-3 py-1.5 text-sm bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`} />
          Sync
        </button>
      </div>

      {/* Sync Status */}
      {syncStatus && syncStatus.status !== 'idle' && (
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-2">
            {syncStatus.status === 'syncing' && (
              <div className="w-2 h-2 bg-primary-500 rounded-full animate-pulse" />
            )}
            {syncStatus.status === 'complete' && (
              <div className="w-2 h-2 bg-green-500 rounded-full" />
            )}
            {syncStatus.status === 'error' && (
              <div className="w-2 h-2 bg-red-500 rounded-full" />
            )}
            <span className="text-sm text-gray-300">{syncStatus.message}</span>
          </div>

          {syncStatus.status === 'syncing' && (
            <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-primary-500 transition-all duration-300"
                style={{ width: `${syncStatus.progress}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Stats */}
      {stats && (
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500">Songs</span>
            <span className="text-gray-300">{stats.total_songs.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Liked</span>
            <span className="text-gray-300">{stats.liked_songs.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Artists</span>
            <span className="text-gray-300">{stats.total_artists.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Genres</span>
            <span className="text-gray-300">{stats.total_genres.toLocaleString()}</span>
          </div>
          <div className="flex justify-between pt-2 border-t border-gray-700">
            <span className="text-gray-500">Last synced</span>
            <span className="text-gray-400">{formatDate(stats.last_synced)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
