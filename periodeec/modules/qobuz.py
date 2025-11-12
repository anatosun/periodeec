import os
import logging
import sys
import re
from typing import Optional
from difflib import SequenceMatcher
from qobuz_dl.core import QobuzDL
from periodeec.modules.downloader import Downloader, MatchResult, DownloadResult
import contextlib


@contextlib.contextmanager
def suppress_stdout_stderr():
    """Suppress stdout and stderr output within context."""
    with open(os.devnull, 'w') as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


logger = logging.getLogger(__name__)


class QobuzInitializationError(Exception):
    """Raised when Qobuz client fails to initialize."""
    pass


class Qobuz(Downloader):
    """Qobuz high-quality music downloader implementation."""

    def __init__(
        self,
        email: str,
        password: str,
        quality: int = 27,
        embed_art: bool = True,
        cover_og_quality: bool = False
    ):
        super().__init__("qobuz-dl")

        if not email or not password:
            raise ValueError("Email and password cannot be empty.")

        self.email = email
        self.quality = quality
        self.qobuz: Optional[QobuzDL] = None

        try:
            self.qobuz = QobuzDL(
                quality=quality,
                embed_art=embed_art,
                cover_og_quality=cover_og_quality
            )
            self.qobuz.get_tokens()
            self.qobuz.initialize_client(
                email, password, self.qobuz.app_id, self.qobuz.secrets
            )
            logger.info(f"{self.name} initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize {self.name}: {e}"
            logger.error(error_msg)
            raise QobuzInitializationError(error_msg) from e

    @staticmethod
    def _normalize_string(text: str) -> str:
        """
        Normalize a string for comparison by removing special characters and extra whitespace.

        Args:
            text: Input string

        Returns:
            Normalized lowercase string
        """
        if not text:
            return ""

        # Remove content in parentheses/brackets (often contains remixes, versions, etc.)
        text = re.sub(r'\([^)]*\)', '', text)
        text = re.sub(r'\[[^\]]*\]', '', text)

        # Remove featuring artists
        text = re.sub(r'\b(feat|featuring|ft|with)\.?\s+[^-]+', '', text, flags=re.IGNORECASE)

        # Remove special characters except spaces and hyphens
        text = re.sub(r'[^\w\s-]', '', text)

        # Normalize whitespace
        text = ' '.join(text.split()).strip().lower()

        return text

    @staticmethod
    def _similarity_score(str1: str, str2: str) -> float:
        """
        Calculate similarity between two strings using SequenceMatcher.

        Args:
            str1: First string
            str2: Second string

        Returns:
            Similarity score between 0.0 and 1.0
        """
        if not str1 or not str2:
            return 0.0

        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()

    def _validate_track_match(
        self,
        track_data: dict,
        artist: str,
        title: str,
        album: str = "",
        release_year: int = 0
    ) -> float:
        """
        Validate a track match against expected metadata and return confidence score.

        Args:
            track_data: Track metadata from Qobuz API
            artist: Expected artist name
            title: Expected track title
            album: Expected album name
            release_year: Expected release year

        Returns:
            Confidence score between 0.0 and 1.0
        """
        score = 0.0
        checks = 0

        # Check artist match
        qobuz_artist = track_data.get('performer', {}).get('name', '') or \
                      track_data.get('album', {}).get('artist', {}).get('name', '')
        if qobuz_artist and artist:
            artist_sim = self._similarity_score(
                self._normalize_string(artist),
                self._normalize_string(qobuz_artist)
            )
            score += artist_sim
            checks += 1

        # Check title match
        qobuz_title = track_data.get('title', '')
        if qobuz_title and title:
            title_sim = self._similarity_score(
                self._normalize_string(title),
                self._normalize_string(qobuz_title)
            )
            score += title_sim
            checks += 1

        # Check album match (if provided)
        if album:
            qobuz_album = track_data.get('album', {}).get('title', '')
            if qobuz_album:
                album_sim = self._similarity_score(
                    self._normalize_string(album),
                    self._normalize_string(qobuz_album)
                )
                score += album_sim
                checks += 1

        # Check release year (if provided)
        if release_year > 0:
            qobuz_year = track_data.get('album', {}).get('release_date_original', '')
            if qobuz_year:
                try:
                    qobuz_year_int = int(qobuz_year.split('-')[0])
                    # Allow 1 year difference
                    if abs(qobuz_year_int - release_year) <= 1:
                        score += 1.0
                    elif abs(qobuz_year_int - release_year) <= 3:
                        score += 0.7
                    else:
                        score += 0.3
                    checks += 1
                except (ValueError, IndexError):
                    pass

        return score / checks if checks > 0 else 0.0

    def match(
        self,
        isrc: str,
        artist: str,
        title: str,
        album: str = "",
        release_year: int = 0
    ) -> MatchResult:
        """
        Match a track on Qobuz using multi-strategy approach with validation.

        Strategy order:
        1. ISRC match (validated against metadata)
        2. Track search by artist + title
        3. Album search by artist + album name
        4. Fuzzy track search with normalized queries

        Args:
            isrc: The ISRC code of the track
            artist: Artist name
            title: Track title
            album: Album name (optional)
            release_year: Release year (optional)

        Returns:
            MatchResult with success status, URL, and confidence score
        """
        if not self.qobuz:
            return MatchResult(
                success=False,
                error_message="Qobuz client not initialized"
            )

        best_match = None
        best_confidence = 0.0

        # Strategy 1: ISRC match with validation (highest confidence)
        if isrc:
            try:
                results = self.qobuz.search_by_type(
                    isrc, item_type="track", lucky=True
                )
                if results and len(results) > 0:
                    track_id = str(results[0]).split("/")[-1]
                    try:
                        track = self.qobuz.client.get_track_meta(track_id)
                        album_url = track.get('album', {}).get('url', '')

                        if album_url:
                            # Validate the match
                            confidence = self._validate_track_match(
                                track, artist, title, album, release_year
                            )

                            # ISRC matches are highly reliable if metadata validates
                            if confidence >= 0.7:
                                confidence = min(0.98, confidence + 0.2)
                                logger.info(
                                    f"{self.name} ISRC match validated "
                                    f"(confidence: {confidence:.2f})"
                                )
                                return MatchResult(
                                    success=True,
                                    url=album_url,
                                    match_method="isrc_validated",
                                    confidence=confidence
                                )
                            elif confidence >= 0.5:
                                best_match = album_url
                                best_confidence = confidence
                                logger.debug(
                                    f"{self.name} ISRC match with moderate confidence: "
                                    f"{confidence:.2f}"
                                )
                    except (KeyError, IndexError) as e:
                        logger.debug(
                            f"{self.name} ISRC match metadata extraction failed: {e}"
                        )
            except Exception as e:
                logger.debug(f"{self.name} ISRC search failed: {e}")

        # Strategy 2: Direct track search (artist + title)
        if artist and title:
            query = f"{artist} {title}"
            try:
                results = self.qobuz.search_by_type(
                    query=query, item_type="track", limit=5
                )

                if results and isinstance(results, dict) and 'tracks' in results:
                    tracks = results['tracks'].get('items', [])

                    for track in tracks[:5]:  # Check top 5 results
                        try:
                            album_url = track.get('album', {}).get('url', '')
                            if not album_url:
                                continue

                            confidence = self._validate_track_match(
                                track, artist, title, album, release_year
                            )

                            if confidence > best_confidence:
                                best_confidence = confidence
                                best_match = album_url

                            # If we found a very good match, use it immediately
                            if confidence >= 0.85:
                                logger.info(
                                    f"{self.name} track search found strong match "
                                    f"(confidence: {confidence:.2f})"
                                )
                                return MatchResult(
                                    success=True,
                                    url=album_url,
                                    match_method="track_search",
                                    confidence=confidence
                                )
                        except (KeyError, TypeError) as e:
                            logger.debug(f"{self.name} error processing track result: {e}")
                            continue

            except Exception as e:
                logger.debug(f"{self.name} track search failed: {e}")

        # Strategy 3: Album search (if album name is provided)
        if artist and album:
            query = f"{artist} {album}"
            try:
                results = self.qobuz.search_by_type(
                    query=query, item_type="album", limit=5
                )

                if results and isinstance(results, dict) and 'albums' in results:
                    albums = results['albums'].get('items', [])

                    for album_data in albums[:5]:
                        try:
                            album_url = album_data.get('url', '')
                            if not album_url:
                                continue

                            # For album search, create pseudo-track data for validation
                            pseudo_track = {
                                'title': title,
                                'album': album_data,
                                'performer': {'name': album_data.get('artist', {}).get('name', '')}
                            }

                            confidence = self._validate_track_match(
                                pseudo_track, artist, title, album, release_year
                            )

                            # Reduce confidence slightly for album-level matches
                            confidence = confidence * 0.9

                            if confidence > best_confidence:
                                best_confidence = confidence
                                best_match = album_url

                            if confidence >= 0.8:
                                logger.info(
                                    f"{self.name} album search found strong match "
                                    f"(confidence: {confidence:.2f})"
                                )
                                return MatchResult(
                                    success=True,
                                    url=album_url,
                                    match_method="album_search",
                                    confidence=confidence
                                )
                        except (KeyError, TypeError) as e:
                            logger.debug(f"{self.name} error processing album result: {e}")
                            continue

            except Exception as e:
                logger.debug(f"{self.name} album search failed: {e}")

        # Strategy 4: Fuzzy search with normalized queries
        if artist and title and best_confidence < 0.7:
            normalized_query = f"{self._normalize_string(artist)} {self._normalize_string(title)}"

            try:
                results = self.qobuz.search_by_type(
                    query=normalized_query, item_type="track", limit=10
                )

                if results and isinstance(results, dict) and 'tracks' in results:
                    tracks = results['tracks'].get('items', [])

                    for track in tracks[:10]:
                        try:
                            album_url = track.get('album', {}).get('url', '')
                            if not album_url:
                                continue

                            confidence = self._validate_track_match(
                                track, artist, title, album, release_year
                            )

                            # Reduce confidence for fuzzy matches
                            confidence = confidence * 0.85

                            if confidence > best_confidence:
                                best_confidence = confidence
                                best_match = album_url

                        except (KeyError, TypeError):
                            continue

            except Exception as e:
                logger.debug(f"{self.name} fuzzy search failed: {e}")

        # Return best match if confidence threshold is met
        if best_match and best_confidence >= 0.6:
            logger.info(
                f"{self.name} matched track: '{artist} - {title}' "
                f"(confidence: {best_confidence:.2f})"
            )
            return MatchResult(
                success=True,
                url=best_match,
                match_method="best_match",
                confidence=best_confidence
            )

        # No suitable match found
        logger.warning(
            f"{self.name} could not match track with sufficient confidence: "
            f"artist='{artist}', title='{title}', album='{album}' "
            f"(best confidence: {best_confidence:.2f})"
        )
        return MatchResult(
            success=False,
            error_message=f"No match found with sufficient confidence (best: {best_confidence:.2f})"
        )

    def enqueue(
        self,
        path: str,
        isrc: str,
        artist: str,
        title: str,
        album: str = "",
        release_year: int = 0
    ) -> DownloadResult:
        """
        Download a matched track/album from Qobuz.

        Args:
            path: Destination directory for downloads
            isrc: Track ISRC code
            artist: Artist name
            title: Track title
            album: Album name (optional, for better matching)
            release_year: Release year (optional, for validation)

        Returns:
            DownloadResult with success status and error details if applicable
        """
        if not self.qobuz:
            return DownloadResult(
                success=False,
                path=path,
                error_message="Qobuz client not initialized"
            )

        # Match the track first with all available metadata
        match_result = self.match(isrc, artist, title, album, release_year)
        if not match_result.success or not match_result.url:
            return DownloadResult(
                success=False,
                path=path,
                error_message=f"No match found for track: {artist} - {title}"
            )

        # Extract album ID from URL
        try:
            album_id = match_result.url.split("/")[-1]
        except (IndexError, AttributeError) as e:
            return DownloadResult(
                success=False,
                path=path,
                error_message=f"Failed to extract album ID from URL: {e}"
            )

        # Create download directory if needed
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
        except OSError as e:
            return DownloadResult(
                success=False,
                path=path,
                error_message=f"Failed to create download directory: {e}"
            )

        # Download the album
        try:
            with suppress_stdout_stderr():
                logger.info(
                    f"{self.name} downloading album '{album_id}' to '{path}'"
                )
                self.qobuz.download_from_id(
                    item_id=album_id, album=True, alt_path=path
                )

            # Check if files were downloaded
            downloaded_files = []
            if os.path.exists(path):
                downloaded_files = [
                    os.path.join(path, f)
                    for f in os.listdir(path)
                    if os.path.isfile(os.path.join(path, f))
                ]

            logger.info(
                f"{self.name} successfully downloaded {len(downloaded_files)} file(s)"
            )
            return DownloadResult(
                success=True,
                path=path,
                downloaded_files=downloaded_files
            )

        except Exception as e:
            error_msg = f"Download failed: {e}"
            logger.error(f"{self.name} {error_msg}")
            return DownloadResult(
                success=False,
                path=path,
                error_message=error_msg
            )

    def _check_availability(self) -> bool:
        """
        Check if Qobuz service is available and authenticated.

        Returns:
            True if the client is properly initialized
        """
        try:
            return self.qobuz is not None and hasattr(self.qobuz, 'client')
        except Exception as e:
            logger.error(f"{self.name} availability check failed: {e}")
            return False
