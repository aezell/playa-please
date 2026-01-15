"""
Feedback service - handles user feedback on songs (likes/dislikes)
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from ..models import Song, UserSong

logger = logging.getLogger(__name__)


class FeedbackService:
    """
    Service for managing user feedback on songs.

    Handles recording likes/dislikes and updating song scores
    based on user feedback.
    """

    # Score multipliers for feedback
    LIKE_SCORE_MULTIPLIER = 1.5
    DISLIKE_SCORE = 0.0
    DEFAULT_SCORE = 1.0

    def __init__(self, db: Session):
        """
        Initialize the feedback service.

        Args:
            db: Database session
        """
        self.db = db

    async def record_feedback(
        self,
        user_id: str,
        video_id: str,
        feedback: str
    ) -> bool:
        """
        Record user feedback for a song and update its score.

        Args:
            user_id: User's ID
            video_id: Song's video ID
            feedback: 'like' or 'dislike'

        Returns:
            True if feedback was recorded successfully

        Raises:
            ValueError: If feedback is not 'like' or 'dislike'
        """
        if feedback not in ('like', 'dislike'):
            raise ValueError(f"Invalid feedback value: {feedback}. Must be 'like' or 'dislike'")

        user_song = self.db.query(UserSong).filter(
            UserSong.user_id == user_id,
            UserSong.video_id == video_id
        ).first()

        now = datetime.utcnow()

        if not user_song:
            # Create new UserSong entry if it doesn't exist
            # Calculate initial score based on feedback
            if feedback == 'like':
                initial_score = self.DEFAULT_SCORE * self.LIKE_SCORE_MULTIPLIER
            else:
                initial_score = self.DISLIKE_SCORE

            user_song = UserSong(
                user_id=user_id,
                video_id=video_id,
                source='feedback',
                feedback=feedback,
                feedback_at=now,
                score=initial_score
            )
            self.db.add(user_song)
            logger.info(f"Created new user_song with feedback '{feedback}' for user {user_id}, video {video_id}")
        else:
            # Update existing entry
            old_feedback = user_song.feedback
            user_song.feedback = feedback
            user_song.feedback_at = now

            # Update score based on new feedback
            self._update_score_for_feedback(user_song, old_feedback, feedback)

            logger.info(f"Updated feedback from '{old_feedback}' to '{feedback}' for user {user_id}, video {video_id}")

        self.db.commit()
        return True

    def _update_score_for_feedback(
        self,
        user_song: UserSong,
        old_feedback: Optional[str],
        new_feedback: str
    ) -> None:
        """
        Update song score when feedback changes.

        The score adjustment depends on the transition:
        - None -> like: score *= 1.5
        - None -> dislike: score = 0
        - like -> dislike: score = 0
        - dislike -> like: score = base * 1.5
        - like -> None: score /= 1.5
        - dislike -> None: score = base

        Args:
            user_song: The UserSong to update
            old_feedback: Previous feedback value
            new_feedback: New feedback value
        """
        if new_feedback == 'dislike':
            # Disliked songs get zero score (excluded from algorithm)
            user_song.score = self.DISLIKE_SCORE
        elif new_feedback == 'like':
            if old_feedback == 'dislike':
                # Coming from dislike, reset to base then apply like multiplier
                user_song.score = self.DEFAULT_SCORE * self.LIKE_SCORE_MULTIPLIER
            elif old_feedback is None:
                # New like, apply multiplier to current score
                user_song.score = (user_song.score or self.DEFAULT_SCORE) * self.LIKE_SCORE_MULTIPLIER

    async def remove_feedback(
        self,
        user_id: str,
        video_id: str
    ) -> bool:
        """
        Remove feedback for a song (set to neutral).

        Args:
            user_id: User's ID
            video_id: Song's video ID

        Returns:
            True if feedback was removed, False if no entry existed
        """
        user_song = self.db.query(UserSong).filter(
            UserSong.user_id == user_id,
            UserSong.video_id == video_id
        ).first()

        if not user_song:
            return False

        old_feedback = user_song.feedback

        if old_feedback is None:
            return True  # Already neutral

        # Reset score based on what feedback was removed
        if old_feedback == 'like':
            # Remove like bonus
            user_song.score = max(
                self.DEFAULT_SCORE,
                (user_song.score or self.DEFAULT_SCORE) / self.LIKE_SCORE_MULTIPLIER
            )
        elif old_feedback == 'dislike':
            # Restore to default score
            user_song.score = self.DEFAULT_SCORE

        user_song.feedback = None
        user_song.feedback_at = None

        self.db.commit()
        logger.info(f"Removed feedback for user {user_id}, video {video_id}")
        return True

    async def get_feedback(
        self,
        user_id: str,
        video_id: str
    ) -> Optional[str]:
        """
        Get user's feedback for a specific song.

        Args:
            user_id: User's ID
            video_id: Song's video ID

        Returns:
            'like', 'dislike', or None if no feedback
        """
        user_song = self.db.query(UserSong).filter(
            UserSong.user_id == user_id,
            UserSong.video_id == video_id
        ).first()

        return user_song.feedback if user_song else None

    async def get_user_feedback(
        self,
        user_id: str
    ) -> Dict[str, str]:
        """
        Get all feedback for a user.

        Args:
            user_id: User's ID

        Returns:
            Dictionary mapping video_id to feedback ('like' or 'dislike')
        """
        user_songs = self.db.query(UserSong).filter(
            UserSong.user_id == user_id,
            UserSong.feedback.isnot(None)
        ).all()

        return {
            user_song.video_id: user_song.feedback
            for user_song in user_songs
            if user_song.feedback is not None
        }

    async def get_liked_songs(
        self,
        user_id: str,
        limit: int = 100
    ) -> List[Song]:
        """
        Get all liked songs for a user.

        Args:
            user_id: User's ID
            limit: Maximum number of songs to return

        Returns:
            List of Song objects that the user has liked
        """
        user_songs = (
            self.db.query(UserSong)
            .options(joinedload(UserSong.song))
            .filter(
                UserSong.user_id == user_id,
                UserSong.feedback == 'like'
            )
            .order_by(UserSong.feedback_at.desc())
            .limit(limit)
            .all()
        )

        return [us.song for us in user_songs if us.song is not None]

    async def get_disliked_songs(
        self,
        user_id: str,
        limit: int = 100
    ) -> List[Song]:
        """
        Get all disliked songs for a user.

        Args:
            user_id: User's ID
            limit: Maximum number of songs to return

        Returns:
            List of Song objects that the user has disliked
        """
        user_songs = (
            self.db.query(UserSong)
            .options(joinedload(UserSong.song))
            .filter(
                UserSong.user_id == user_id,
                UserSong.feedback == 'dislike'
            )
            .order_by(UserSong.feedback_at.desc())
            .limit(limit)
            .all()
        )

        return [us.song for us in user_songs if us.song is not None]

    async def get_feedback_stats(
        self,
        user_id: str
    ) -> Dict[str, int]:
        """
        Get feedback statistics for a user.

        Args:
            user_id: User's ID

        Returns:
            Dictionary with counts: {'liked': int, 'disliked': int, 'neutral': int}
        """
        user_songs = self.db.query(UserSong).filter(
            UserSong.user_id == user_id
        ).all()

        stats = {'liked': 0, 'disliked': 0, 'neutral': 0}

        for user_song in user_songs:
            if user_song.feedback == 'like':
                stats['liked'] += 1
            elif user_song.feedback == 'dislike':
                stats['disliked'] += 1
            else:
                stats['neutral'] += 1

        return stats


# Convenience functions for use without instantiating the service

async def record_feedback(
    user_id: str,
    video_id: str,
    feedback: str,
    db: Session
) -> bool:
    """
    Record user feedback for a song.

    Args:
        user_id: User's ID
        video_id: Song's video ID
        feedback: 'like' or 'dislike'
        db: Database session

    Returns:
        True if feedback was recorded
    """
    service = FeedbackService(db)
    return await service.record_feedback(user_id, video_id, feedback)


async def get_user_feedback(
    user_id: str,
    db: Session
) -> Dict[str, str]:
    """
    Get all feedback for a user.

    Args:
        user_id: User's ID
        db: Database session

    Returns:
        Dictionary mapping video_id to feedback
    """
    service = FeedbackService(db)
    return await service.get_user_feedback(user_id)


async def remove_feedback(
    user_id: str,
    video_id: str,
    db: Session
) -> bool:
    """
    Remove feedback for a song.

    Args:
        user_id: User's ID
        video_id: Song's video ID
        db: Database session

    Returns:
        True if feedback was removed
    """
    service = FeedbackService(db)
    return await service.remove_feedback(user_id, video_id)
