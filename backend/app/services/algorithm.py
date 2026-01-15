"""
Playlist Algorithm Service - Core playlist generation logic
"""
import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import PlaylistQueue, Song, UserSong, UnavailableVideo

logger = logging.getLogger(__name__)
settings = get_settings()


class PlaylistAlgorithm:
    """
    Intelligent playlist generation algorithm with diversity constraints.

    The algorithm balances several factors:
    1. Artist diversity - No same artist within min_artist_gap songs
    2. Genre balance - No genre exceeds max_genre_ratio of recent songs
    3. Discovery mix - discovery_ratio of songs should be "discoveries"
    4. Feedback boost - Liked songs get higher scores, disliked excluded
    5. Recency decay - Recent plays reduce score
    6. Randomization - Controlled randomness prevents predictability
    """

    def __init__(self, user_id: str, db: Session):
        """
        Initialize the algorithm for a specific user.

        Args:
            user_id: The user ID to generate playlist for
            db: Database session
        """
        self.user_id = user_id
        self.db = db
        self.settings = settings

        # Cache for efficiency
        self._candidates_cache: Optional[List[UserSong]] = None
        self._feedback_cache: Optional[Dict[str, str]] = None

    def generate_queue(self, count: Optional[int] = None) -> List[Song]:
        """
        Generate the next batch of songs with diversity constraints.

        Args:
            count: Number of songs to generate (defaults to queue_prefetch_size)

        Returns:
            List of Song objects for the queue
        """
        if count is None:
            count = self.settings.queue_prefetch_size

        # Get recently played songs for diversity context
        recent_songs = self._get_recent_plays(count=count * 2)

        # Get all candidate songs
        candidates = self._get_candidate_songs()

        if not candidates:
            logger.warning(f"No candidate songs found for user {self.user_id}")
            return []

        # Build context for scoring
        context = self._build_context(recent_songs)

        # Score all candidates
        scored_candidates = []
        for candidate in candidates:
            score = self._calculate_score(candidate, context)
            if score > 0:  # Exclude disliked songs (score = 0)
                scored_candidates.append((candidate, score))

        # Apply diversity constraints and select songs
        selected = self._select_diverse_songs(scored_candidates, recent_songs, count)

        # Convert UserSong to Song objects
        result = []
        for user_song in selected:
            if user_song.song:
                result.append(user_song.song)

        logger.info(f"Generated {len(result)} songs for user {self.user_id}")
        return result

    def _get_candidate_songs(self) -> List[UserSong]:
        """
        Get all songs available for the user, excluding unavailable videos.

        Returns:
            List of UserSong objects with their associated Song data
        """
        if self._candidates_cache is not None:
            return self._candidates_cache

        # Get unavailable video IDs (permanent ones only, not bot_detection with retry)
        unavailable_ids = set(
            row.video_id for row in
            self.db.query(UnavailableVideo.video_id).filter(
                (UnavailableVideo.error_type == 'unavailable') |
                ((UnavailableVideo.error_type == 'bot_detection') &
                 (UnavailableVideo.retry_after > datetime.utcnow()))
            ).all()
        )

        candidates = (
            self.db.query(UserSong)
            .options(joinedload(UserSong.song))
            .filter(
                UserSong.user_id == self.user_id,
                ~UserSong.video_id.in_(unavailable_ids) if unavailable_ids else True
            )
            .all()
        )

        self._candidates_cache = candidates
        return candidates

    def _get_recent_plays(self, count: int = 50) -> List[UserSong]:
        """
        Get the most recently played songs.

        Args:
            count: Number of recent songs to retrieve

        Returns:
            List of recently played UserSong objects
        """
        return (
            self.db.query(UserSong)
            .options(joinedload(UserSong.song))
            .filter(
                UserSong.user_id == self.user_id,
                UserSong.last_played.isnot(None)
            )
            .order_by(UserSong.last_played.desc())
            .limit(count)
            .all()
        )

    def _build_context(self, recent_songs: List[UserSong]) -> dict:
        """
        Build context dictionary for scoring decisions.

        Args:
            recent_songs: List of recently played songs

        Returns:
            Context dictionary with genre counts, recent artists, etc.
        """
        context = {
            'genre_counts': defaultdict(int),
            'recent_artists': [],
            'recent_video_ids': set(),
            'total_recent': len(recent_songs),
            'now': datetime.utcnow(),
        }

        for user_song in recent_songs:
            if user_song.song:
                # Track recent artists
                context['recent_artists'].append(user_song.song.artist_id or user_song.song.artist)
                context['recent_video_ids'].add(user_song.video_id)

                # Count genres
                try:
                    genres = json.loads(user_song.song.genres) if user_song.song.genres else []
                except (json.JSONDecodeError, TypeError):
                    genres = []

                for genre in genres:
                    context['genre_counts'][genre] += 1

        return context

    def _calculate_score(self, song: UserSong, context: dict) -> float:
        """
        Score a song based on preference and diversity factors.

        Scoring formula:
        - base_score = 1.0
        - if liked: base_score *= 1.5
        - if disliked: return 0 (excluded)
        - if last_played > 30 days ago: base_score *= 1.3 (rediscovery bonus)
        - if high play_count: base_score *= 1.1
        - recency_penalty = max(0.1, 1 - (1 / days_since_played)) if recently played
        - final_score = base_score * recency_penalty * random(0.8, 1.2)

        Args:
            song: The UserSong to score
            context: Context dictionary with recent play info

        Returns:
            Score value (0 = excluded, higher = more preferred)
        """
        # Exclude disliked songs
        if song.feedback == 'dislike':
            return 0.0

        base_score = 1.0

        # Liked songs get boost
        if song.feedback == 'like':
            base_score *= 1.5

        now = context['now']

        # Calculate days since last played
        if song.last_played:
            days_since_played = (now - song.last_played).total_seconds() / 86400
        else:
            days_since_played = float('inf')  # Never played

        # Rediscovery bonus for songs not played in 30+ days
        if days_since_played > 30:
            base_score *= 1.3

        # Play count boost (popular personal songs)
        if song.play_count and song.play_count >= 5:
            base_score *= 1.1

        # Recency penalty - avoid immediate repeats
        if days_since_played < 7:
            # Strong penalty for very recent plays
            if days_since_played < 1:
                recency_penalty = 0.1
            else:
                recency_penalty = max(0.1, 1 - (1 / days_since_played))
        else:
            recency_penalty = 1.0

        # Apply randomization (0.8 to 1.2)
        randomness = random.uniform(0.8, 1.2)

        final_score = base_score * recency_penalty * randomness

        return final_score

    def _apply_diversity_constraints(
        self,
        candidate: UserSong,
        recent_artists: List[str],
        genre_counts: Dict[str, int],
        total_in_window: int
    ) -> bool:
        """
        Check if a song violates diversity rules.

        Args:
            candidate: The candidate song to check
            recent_artists: List of recent artist IDs (most recent first)
            genre_counts: Current genre distribution in selection window
            total_in_window: Total songs in the current window

        Returns:
            True if song passes constraints, False if it should be filtered
        """
        if not candidate.song:
            return False

        # Artist diversity check
        artist_id = candidate.song.artist_id or candidate.song.artist
        if artist_id in recent_artists[:self.settings.min_artist_gap]:
            return False

        # Genre balance check
        if total_in_window > 0:
            try:
                song_genres = json.loads(candidate.song.genres) if candidate.song.genres else []
            except (json.JSONDecodeError, TypeError):
                song_genres = []

            for genre in song_genres:
                genre_ratio = genre_counts.get(genre, 0) / total_in_window
                if genre_ratio >= self.settings.max_genre_ratio:
                    return False

        return True

    def _select_diverse_songs(
        self,
        scored_candidates: List[Tuple[UserSong, float]],
        recent_songs: List[UserSong],
        count: int
    ) -> List[UserSong]:
        """
        Select songs while maintaining diversity constraints.

        Implements discovery ratio by selecting a mix of "familiar" and
        "discovery" songs based on the configured ratio.

        Args:
            scored_candidates: List of (UserSong, score) tuples
            recent_songs: Recently played songs for context
            count: Target number of songs to select

        Returns:
            List of selected UserSong objects
        """
        # Separate into discoveries and familiar songs
        discoveries = []
        familiar = []
        now = datetime.utcnow()

        for candidate, score in scored_candidates:
            if candidate.last_played is None:
                # Never played = discovery
                discoveries.append((candidate, score))
            elif (now - candidate.last_played).days > 30:
                # Not played in 30+ days = rediscovery
                discoveries.append((candidate, score))
            else:
                familiar.append((candidate, score))

        # Sort both lists by score (descending)
        discoveries.sort(key=lambda x: x[1], reverse=True)
        familiar.sort(key=lambda x: x[1], reverse=True)

        # Calculate target counts based on discovery_ratio
        target_discoveries = int(count * self.settings.discovery_ratio)
        target_familiar = count - target_discoveries

        # Build initial artist tracking from recent songs
        recent_artists = []
        for user_song in recent_songs:
            if user_song.song:
                recent_artists.append(user_song.song.artist_id or user_song.song.artist)

        # Build initial genre counts from recent songs
        genre_counts = defaultdict(int)
        for user_song in recent_songs:
            if user_song.song:
                try:
                    genres = json.loads(user_song.song.genres) if user_song.song.genres else []
                except (json.JSONDecodeError, TypeError):
                    genres = []
                for genre in genres:
                    genre_counts[genre] += 1

        selected = []
        selected_video_ids = set()

        # Helper to select from a pool while respecting constraints
        def select_from_pool(pool: List[Tuple[UserSong, float]], target: int) -> List[UserSong]:
            result = []
            for candidate, score in pool:
                if len(result) >= target:
                    break

                if candidate.video_id in selected_video_ids:
                    continue

                # Check diversity constraints
                total_window = len(recent_artists) + len(selected)
                if not self._apply_diversity_constraints(
                    candidate,
                    recent_artists + [s.song.artist_id or s.song.artist for s in result if s.song],
                    genre_counts,
                    total_window
                ):
                    continue

                result.append(candidate)
                selected_video_ids.add(candidate.video_id)

                # Update tracking
                if candidate.song:
                    try:
                        genres = json.loads(candidate.song.genres) if candidate.song.genres else []
                    except (json.JSONDecodeError, TypeError):
                        genres = []
                    for genre in genres:
                        genre_counts[genre] += 1

            return result

        # Select discoveries first
        discovery_selected = select_from_pool(discoveries, target_discoveries)
        selected.extend(discovery_selected)

        # Select familiar songs
        familiar_selected = select_from_pool(familiar, target_familiar)
        selected.extend(familiar_selected)

        # If we don't have enough, fill from any remaining candidates
        if len(selected) < count:
            remaining = [c for c in scored_candidates if c[0].video_id not in selected_video_ids]
            remaining.sort(key=lambda x: x[1], reverse=True)
            additional = select_from_pool(remaining, count - len(selected))
            selected.extend(additional)

        # Shuffle to mix discoveries and familiar (but keep some score weighting)
        random.shuffle(selected)

        return selected

    def is_discovery(self, song: UserSong) -> bool:
        """
        Check if a song qualifies as a "discovery".

        A song is a discovery if:
        - Never played before, OR
        - Not played in the last 30 days

        Args:
            song: The UserSong to check

        Returns:
            True if the song is a discovery
        """
        if song.last_played is None:
            return True
        return (datetime.utcnow() - song.last_played).days > 30

    def update_queue(self, songs: List[Song]) -> List[PlaylistQueue]:
        """
        Update the user's playlist queue with new songs.

        Clears unplayed queue items and adds new songs.

        Args:
            songs: List of Song objects to add to queue

        Returns:
            List of created PlaylistQueue entries
        """
        # Clear existing unplayed queue items
        self.db.query(PlaylistQueue).filter(
            PlaylistQueue.user_id == self.user_id,
            PlaylistQueue.played == False
        ).delete()

        # Get current max position
        max_pos = (
            self.db.query(PlaylistQueue.position)
            .filter(PlaylistQueue.user_id == self.user_id)
            .order_by(PlaylistQueue.position.desc())
            .first()
        )
        start_position = (max_pos[0] + 1) if max_pos else 0

        # Add new songs to queue
        queue_entries = []
        for i, song in enumerate(songs):
            entry = PlaylistQueue(
                user_id=self.user_id,
                video_id=song.video_id,
                position=start_position + i,
                played=False,
                created_at=datetime.utcnow()
            )
            self.db.add(entry)
            queue_entries.append(entry)

        self.db.commit()
        return queue_entries

    def get_queue(self, limit: int = 20) -> List[Song]:
        """
        Get the current queue for the user.

        Args:
            limit: Maximum number of songs to return

        Returns:
            List of Song objects in queue order
        """
        queue_entries = (
            self.db.query(PlaylistQueue)
            .filter(
                PlaylistQueue.user_id == self.user_id,
                PlaylistQueue.played == False
            )
            .order_by(PlaylistQueue.position)
            .limit(limit)
            .all()
        )

        # Get the songs for these entries
        video_ids = [entry.video_id for entry in queue_entries]
        songs = (
            self.db.query(Song)
            .filter(Song.video_id.in_(video_ids))
            .all()
        )

        # Create a lookup map
        song_map = {song.video_id: song for song in songs}

        # Return in queue order
        return [song_map[entry.video_id] for entry in queue_entries if entry.video_id in song_map]

    def mark_song_played(self, video_id: str) -> bool:
        """
        Mark a song as played in the queue.

        Args:
            video_id: The video ID to mark as played

        Returns:
            True if the song was found and marked
        """
        queue_entry = (
            self.db.query(PlaylistQueue)
            .filter(
                PlaylistQueue.user_id == self.user_id,
                PlaylistQueue.video_id == video_id,
                PlaylistQueue.played == False
            )
            .first()
        )

        if queue_entry:
            queue_entry.played = True
            # Also update UserSong last_played
            from ..models import UserSong
            user_song = self.db.query(UserSong).filter(
                UserSong.user_id == self.user_id,
                UserSong.video_id == video_id
            ).first()
            if user_song:
                from datetime import datetime
                user_song.last_played = datetime.utcnow()
                user_song.play_count = (user_song.play_count or 0) + 1
            return True
        return False

    async def update_song_score(self, video_id: str, event: str) -> float:
        """
        Update song score based on user interaction.

        Events:
        - 'played': Song was played through
        - 'skipped': Song was skipped
        - 'liked': User liked the song
        - 'disliked': User disliked the song

        Args:
            video_id: The song's video ID
            event: Type of interaction

        Returns:
            New score value
        """
        user_song = self.db.query(UserSong).filter(
            UserSong.user_id == self.user_id,
            UserSong.video_id == video_id
        ).first()

        if not user_song:
            return 1.0

        # Adjust score based on event
        if event == 'played':
            user_song.score = min(2.0, user_song.score * 1.05)
            user_song.play_count = (user_song.play_count or 0) + 1
            user_song.last_played = datetime.utcnow()
        elif event == 'skipped':
            user_song.score = max(0.5, user_song.score * 0.95)
        elif event == 'liked':
            user_song.score = min(2.0, user_song.score * 1.5)
            user_song.feedback = 'like'
            user_song.feedback_at = datetime.utcnow()
        elif event == 'disliked':
            user_song.score = 0.0
            user_song.feedback = 'dislike'
            user_song.feedback_at = datetime.utcnow()

        self.db.commit()
        return user_song.score


async def generate_playlist(db: Session, user_id: str, count: Optional[int] = None) -> List[Song]:
    """
    Convenience function to generate a playlist for a user.

    Args:
        db: Database session
        user_id: The user ID
        count: Optional song count

    Returns:
        List of Song objects
    """
    algorithm = PlaylistAlgorithm(user_id, db)
    songs = algorithm.generate_queue(count)
    if songs:
        algorithm.update_queue(songs)
    return songs
