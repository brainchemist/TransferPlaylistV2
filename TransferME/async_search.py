# async_search.py
import asyncio
import aiohttp
import time
import os
from typing import List, Dict, Optional, Tuple, Callable
from database import get_db, SearchCache, TransferHistory
from token_manager import token_manager
import re
import json

SOUNDCLOUD_CLIENT_ID = os.getenv("SCCLIENT_ID")

class AsyncTrackSearcher:
    def __init__(self):
        self.session = None
        self.rate_limits = {
            'spotify': {'requests': 0, 'reset_time': 0, 'limit': 100},
            'soundcloud': {'requests': 0, 'reset_time': 0, 'limit': 50}
        }

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _wait_for_rate_limit(self, platform: str):
        """Wait if rate limit exceeded"""
        rate_info = self.rate_limits[platform]
        current_time = time.time()
        
        if current_time < rate_info['reset_time']:
            if rate_info['requests'] >= rate_info['limit']:
                wait_time = rate_info['reset_time'] - current_time
                time.sleep(wait_time)
                rate_info['requests'] = 0
                rate_info['reset_time'] = current_time + 3600
        elif current_time >= rate_info['reset_time']:
            rate_info['requests'] = 0
            rate_info['reset_time'] = current_time + 3600

    async def _search_soundcloud_track(self, session_id: str, track_name: str, artist_name: str) -> Optional[Dict]:
        """Search for a track on SoundCloud with OAuth authentication"""
        try:
            # Get the SoundCloud access token for this session
            soundcloud_token = token_manager.get_soundcloud_token(session_id)
            if not soundcloud_token:
                print(f"SoundCloud search error: No SoundCloud token for session {session_id}")
                return None

            self._wait_for_rate_limit('soundcloud')
            
            query = f"{track_name} {artist_name}".strip()
            
            # Prepare headers with OAuth token
            headers = {
                'Authorization': f'OAuth {soundcloud_token}',
                'Accept': 'application/json; charset=utf-8'
            }
            
            # Prepare search parameters
            params = {
                'q': query,
                'limit': 10,
                'offset': 0
            }

            # Try v2 API first (with OAuth token in header)
            async with self.session.get(
                'https://api-v2.soundcloud.com/search/tracks',
                headers=headers,
                params=params
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    tracks = data.get('collection', [])
                else:
                    # Fallback to v1 API (also with OAuth token)
                    async with self.session.get(
                        'https://api.soundcloud.com/tracks',
                        headers=headers,
                        params=params
                    ) as fallback_response:
                        if fallback_response.status != 200:
                            error_text = await fallback_response.text()
                            print(f"SoundCloud API error: {fallback_response.status} - {error_text}")
                            return None
                        data = await fallback_response.json()
                        tracks = data if isinstance(data, list) else data.get('collection', [])
                
                if not tracks:
                    return None

                # Find best match using fuzzy matching
                best_match = None
                best_score = 0.0
                
                for track in tracks:
                    track_title = track.get('title', '').lower()
                    track_user = track.get('user', {}).get('username', '').lower() if track.get('user') else ''
                    
                    # Simple fuzzy matching score
                    title_score = self._fuzzy_match(track_name.lower(), track_title)
                    artist_score = self._fuzzy_match(artist_name.lower(), track_user)
                    
                    combined_score = (title_score * 0.7) + (artist_score * 0.3)
                    
                    if combined_score > best_score and combined_score > 0.5:  # Minimum threshold
                        best_score = combined_score
                        best_match = {
                            'id': track.get('id'),
                            'title': track.get('title'),
                            'artist': track_user,
                            'url': track.get('permalink_url'),
                            'match_score': combined_score
                        }
                
                # Update rate limit info
                self.rate_limits['soundcloud']['requests'] += 1
                return best_match

        except Exception as e:
            print(f"SoundCloud search error: {str(e)}")
            return None

    def _fuzzy_match(self, query: str, target: str) -> float:
        """Simple fuzzy string matching"""
        if not query or not target:
            return 0.0
        
        # Remove special characters and normalize
        import re
        query_clean = re.sub(r'[^\w\s]', '', query).lower().strip()
        target_clean = re.sub(r'[^\w\s]', '', target).lower().strip()
        
        if query_clean == target_clean:
            return 1.0
        
        if query_clean in target_clean or target_clean in query_clean:
            return 0.8
        
        # Word-based matching
        query_words = set(query_clean.split())
        target_words = set(target_clean.split())
        
        if not query_words or not target_words:
            return 0.0
        
        intersection = query_words.intersection(target_words)
        union = query_words.union(target_words)
        
        return len(intersection) / len(union) if union else 0.0

    async def batch_search_tracks(
        self,
        session_id: str,
        track_list: List[Tuple[str, str]],
        destination_platform: str,
        progress_callback: Optional[Callable] = None
    ) -> List[Optional[Dict]]:
        """Search for multiple tracks asynchronously"""
        
        results = []
        total_tracks = len(track_list)
        
        for i, (track_name, artist_name) in enumerate(track_list):
            if destination_platform.lower() == 'soundcloud':
                result = await self._search_soundcloud_track(session_id, track_name, artist_name)
            else:
                result = None  # Add other platforms as needed
            
            results.append(result)
            
            if progress_callback:
                progress_callback(i + 1, total_tracks, f"Searched: {track_name} - {artist_name}")
            
            # Small delay to be respectful to APIs
            await asyncio.sleep(0.1)
        
        return results

async def transfer_playlist_async(
    session_id: str,
    track_list: List[Tuple[str, str]],
    source_platform: str,
    destination_platform: str,
    progress_callback: Optional[Callable] = None
) -> Dict:
    """Async playlist transfer with progress tracking"""
    
    async with AsyncTrackSearcher() as searcher:
        # Search for tracks on destination platform
        search_results = await searcher.batch_search_tracks(
            session_id, 
            track_list, 
            destination_platform,
            progress_callback
        )
        
        # Filter successful matches
        found_tracks = [
            result for result in search_results 
            if result and not isinstance(result, Exception)
        ]
        
        return {
            'total_tracks': len(track_list),
            'found_tracks': len(found_tracks),
            'success_rate': len(found_tracks) / len(track_list) if track_list else 0,
            'tracks': found_tracks
        }
