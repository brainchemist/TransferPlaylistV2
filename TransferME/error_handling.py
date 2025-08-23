# error_handling.py
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ErrorType(Enum):
    AUTH_EXPIRED = "auth_expired"
    AUTH_MISSING = "auth_missing"
    PLAYLIST_NOT_FOUND = "playlist_not_found"
    PLAYLIST_PRIVATE = "playlist_private"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class TransferError:
    error_type: ErrorType
    message: str
    details: Optional[str] = None
    recoverable: bool = True
    retry_after: Optional[int] = None  # seconds to wait before retry

@dataclass
class TransferResult:
    success: bool
    tracks_total: int = 0
    tracks_found: int = 0
    tracks_created: int = 0
    playlist_url: Optional[str] = None
    error: Optional[TransferError] = None
    warnings: list = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
    
    @property
    def success_rate(self) -> float:
        if self.tracks_total == 0:
            return 0.0
        return self.tracks_found / self.tracks_total
    
    @property
    def status_message(self) -> str:
        if not self.success:
            return f"❌ {self.error.message if self.error else 'Transfer failed'}"
        elif self.tracks_found == self.tracks_total:
            return f"✅ Successfully transferred all {self.tracks_found} tracks!"
        else:
            return f"⚠️ Partially successful: {self.tracks_found}/{self.tracks_total} tracks transferred"

class ErrorHandler:
    """Centralized error handling for the application"""
    
    @staticmethod
    def handle_spotify_error(response_code: int, response_text: str) -> TransferError:
        """Handle Spotify API errors"""
        if response_code == 401:
            return TransferError(
                error_type=ErrorType.AUTH_EXPIRED,
                message="Spotify authentication expired",
                details="Please re-authenticate with Spotify",
                recoverable=True
            )
        elif response_code == 403:
            return TransferError(
                error_type=ErrorType.PLAYLIST_PRIVATE,
                message="Cannot access private playlist",
                details="Make sure the playlist is public or you have access",
                recoverable=False
            )
        elif response_code == 404:
            return TransferError(
                error_type=ErrorType.PLAYLIST_NOT_FOUND,
                message="Spotify playlist not found",
                details="Check that the playlist URL is correct",
                recoverable=False
            )
        elif response_code == 429:
            return TransferError(
                error_type=ErrorType.RATE_LIMITED,
                message="Spotify rate limit exceeded",
                details="Too many requests, please try again later",
                recoverable=True,
                retry_after=60
            )
        else:
            return TransferError(
                error_type=ErrorType.API_ERROR,
                message=f"Spotify API error: {response_code}",
                details=response_text[:200],
                recoverable=True
            )
    
    @staticmethod
    def handle_soundcloud_error(response_code: int, response_text: str) -> TransferError:
        """Handle SoundCloud API errors"""
        if response_code == 401:
            return TransferError(
                error_type=ErrorType.AUTH_EXPIRED,
                message="SoundCloud authentication expired",
                details="Please re-authenticate with SoundCloud",
                recoverable=True
            )
        elif response_code == 403:
            return TransferError(
                error_type=ErrorType.PLAYLIST_PRIVATE,
                message="Cannot access SoundCloud resource",
                details="Check permissions and playlist privacy",
                recoverable=False
            )
        elif response_code == 404:
            return TransferError(
                error_type=ErrorType.PLAYLIST_NOT_FOUND,
                message="SoundCloud playlist not found",
                details="Check that the playlist URL is correct",
                recoverable=False
            )
        elif response_code == 429:
            return TransferError(
                error_type=ErrorType.RATE_LIMITED,
                message="SoundCloud rate limit exceeded",
                details="Too many requests, please try again later",
                recoverable=True,
                retry_after=60
            )
        else:
            return TransferError(
                error_type=ErrorType.API_ERROR,
                message=f"SoundCloud API error: {response_code}",
                details=response_text[:200],
                recoverable=True
            )
    
    @staticmethod
    def handle_network_error(exception: Exception) -> TransferError:
        """Handle network-related errors"""
        return TransferError(
            error_type=ErrorType.NETWORK_ERROR,
            message="Network connection failed",
            details=str(exception),
            recoverable=True,
            retry_after=30
        )
    
    @staticmethod
    def handle_validation_error(message: str) -> TransferError:
        """Handle input validation errors"""
        return TransferError(
            error_type=ErrorType.VALIDATION_ERROR,
            message=message,
            recoverable=False
        )
    
    @staticmethod
    def handle_unknown_error(exception: Exception) -> TransferError:
        """Handle unexpected errors"""
        logger.error(f"Unknown error: {str(exception)}\n{traceback.format_exc()}")
        return TransferError(
            error_type=ErrorType.UNKNOWN_ERROR,
            message="An unexpected error occurred",
            details=str(exception),
            recoverable=True
        )

class RetryManager:
    """Manage retry logic for failed operations"""
    
    def __init__(self, max_retries: int = 3, base_delay: int = 1):
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    async def retry_operation(self, operation, *args, **kwargs):
        """Retry an async operation with exponential backoff"""
        import asyncio
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {str(e)}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {self.max_retries + 1} attempts failed")
        
        raise last_error

def validate_playlist_url(url: str, platform: str) -> Optional[TransferError]:
    """Validate playlist URL format"""
    if platform == "spotify":
        if "open.spotify.com/playlist/" not in url:
            return ErrorHandler.handle_validation_error(
                "Invalid Spotify URL. Please provide a valid Spotify playlist URL."
            )
    elif platform == "soundcloud":
        if "soundcloud.com" not in url or "/sets/" not in url:
            return ErrorHandler.handle_validation_error(
                "Invalid SoundCloud URL. Please provide a valid SoundCloud playlist URL."
            )
    
    return None

def log_transfer_attempt(session_id: str, source: str, destination: str, playlist_url: str):
    """Log transfer attempt for debugging"""
    logger.info(f"Transfer attempt - Session: {session_id}, {source} → {destination}, URL: {playlist_url}")

def log_transfer_result(session_id: str, result: TransferResult):
    """Log transfer result for monitoring"""
    if result.success:
        logger.info(f"Transfer success - Session: {session_id}, {result.tracks_found}/{result.tracks_total} tracks")
    else:
        logger.error(f"Transfer failed - Session: {session_id}, Error: {result.error.message if result.error else 'Unknown'}")

# Utility functions for common error patterns
def is_auth_error(error: TransferError) -> bool:
    return error.error_type in [ErrorType.AUTH_EXPIRED, ErrorType.AUTH_MISSING]

def is_retryable_error(error: TransferError) -> bool:
    return error.recoverable and error.error_type in [
        ErrorType.RATE_LIMITED,
        ErrorType.NETWORK_ERROR,
        ErrorType.API_ERROR,
        ErrorType.AUTH_EXPIRED
    ]

def get_user_friendly_message(error: TransferError) -> str:
    """Convert technical errors to user-friendly messages"""
    friendly_messages = {
        ErrorType.AUTH_EXPIRED: "🔑 Please reconnect your account and try again",
        ErrorType.AUTH_MISSING: "🔑 Please connect your account first",
        ErrorType.PLAYLIST_NOT_FOUND: "🔍 Playlist not found - check the URL",
        ErrorType.PLAYLIST_PRIVATE: "🔒 Cannot access private playlist",
        ErrorType.RATE_LIMITED: "⏳ Too many requests - please wait a moment",
        ErrorType.NETWORK_ERROR: "🌐 Connection issue - please try again",
        ErrorType.API_ERROR: "⚠️ Service temporarily unavailable",
        ErrorType.VALIDATION_ERROR: "❌ Invalid input provided",
        ErrorType.UNKNOWN_ERROR: "🛠️ Something went wrong - please try again"
    }
    
    base_message = friendly_messages.get(error.error_type, error.message)
    if error.details and error.error_type == ErrorType.VALIDATION_ERROR:
        return f"{base_message}: {error.details}"
    return base_message