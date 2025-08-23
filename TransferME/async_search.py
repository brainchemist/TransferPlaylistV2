# async_search.py
import asyncio
import aiohttp
import time
from typing import List, Dict, Optional, Tuple, Callable
from database import get_db, SearchCache, TransferHistory
from token_manager import token_manager
import re
import json

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

    def _normalize_string(self, s: str) -> str:
        """Normalize string for matching"""
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"\b(slowed|reverb|remix|edit|radio|version|feat|ft)\b", "", s)
        return s

    def _calculate_match_score(self, target: str, candidate: str) -> float:
        """Calculate similarity score between two strings"""
        target_norm = self._normalize_string(target)
        candidate_norm = self._normalize_string(candidate)
        
        target_words = set(target_norm.split())
        candidate_words = set(candidate_norm.split())
        
        if not target_words or not candidate_words:
            return 0.0
        
        intersection = target_words & candidate_words
        union = target_words | candidate_words
        
        return len(intersection) / len(union)

    def _check_rate_limit(self, platform: str) -> bool:
        """Check if we're within rate limits"""
        now = time.time()
        rate_info = self.rate_limits[platform]
        
        if now > rate_info['reset_time']:
            rate_info['requests'] = 0
            rate_info['reset_time'] = now + 60  # Reset every minute
        
        if rate_info['requests'] >= rate_info['limit']:
            return False
        
        rate_info['requests'] += 1
        return True

    async def _search_cache(self, query: str, platform: str) -> Optional[Dict]:
        """Check cache for previous search results"""
        db = next(get_db())
        try:
            cached = db.query(SearchCache).filter(
                SearchCache.query == query,
                SearchCache.platform == platform
            ).first()
            
            if cached:
                return {
                    'id': cached.result_track_id,
                    'title': cached.result_title,
                    'artist': cached.result_artist,
                    'match_score': float(cached.match_score)
                }
        finally:
            db.close()
        return None

    async def _cache_result(self, query: str, platform: str, result: Dict) -> None:
        """Cache search result"""
        db = next(get_db())
        try:
            cache_entry = SearchCache(
                query=query,
                platform=platform,
                result_track_id=result.get('id', ''),
                result_title=result.get('title', ''),
                result_artist=result.get('artist', ''),
                match_score=str(result.get('match_score', 0.0))
            )
            db.add(cache_entry)
            db.commit()
        finally:
            db.close()

    async def search_spotify_track(self, session_id: str, title: str, artist: str) -> Optional[Dict]:
        """Search for track on Spotify with caching and rate limiting"""
        query = f"{title} {artist}".strip()
        
        # Check cache first
        cached = await self._search_cache(query, 'spotify')
        if cached:
            return cached
        
        # Check rate limit
        if not self._check_rate_limit('spotify'):
            await asyncio.sleep(60)  # Wait for rate limit reset
        
        token = token_manager.get_spotify_token(session_id)
        if not token:
            return None
        
        try:
            headers = {'Authorization': f'Bearer {token}'}
            params = {'q': query, 'type': 'track', 'limit': 10}
            
            async with self.session.get(
                'https://api.spotify.com/v1/search',
                headers=headers,
                params=params
            ) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                tracks = data.get('tracks', {}).get('items', [])
                
                if not tracks:
                    return None
                
                # Find best match
                best_match = None
                best_score = 0.0
                
                for track in tracks:
                    track_title = track['name']
                    track_artist = track['artists'][0]['name'] if track['artists'] else ''
                    candidate = f"{track_title} {track_artist}"
                    
                    score = self._calculate_match_score(query, candidate)
                    if score > best_score:
                        best_score = score
                        best_match = {
                            'id': track['id'],
                            'title': track_title,
                            'artist': track_artist,
                            'match_score': score
                        }
                
                if best_match and best_score >= 0.5:
                    await self._cache_result(query, 'spotify', best_match)
                    return best_match
                
        except Exception as e:
            print(f"Spotify search error: {e}")
        
        return None

    async def search_soundcloud_track(self, session_id: str, title: str, artist: str) -> Optional[Dict]:
        """Search for track on SoundCloud with caching and rate limiting"""
        query = f"{title} {artist}".strip()
        
        # Check cache first
        cached = await self._search_cache(query, 'soundcloud')
        if cached:
            return cached
        
        # Check rate limit
        if not self._check_rate_limit('soundcloud'):
            await asyncio.sleep(60)
        
        token = token_manager.get_soundcloud_token(session_id)
        if not token:
            return None
        
        try:
            headers = {'Authorization': f'OAuth {token}'}
            params = {'q': query, 'limit': 10}
            
            # Try v2 API first
            async with self.session.get(
                'https://api-v2.soundcloud.com/search/tracks',
                headers=headers,
                params=params
            ) as response:
                if response.status != 200:
                    # Fallback to v1 API
                    params['client_id'] = token_manager.SOUNDCLOUD_CLIENT_ID
                    async with self.session.get(
                        'https://api.soundcloud.com/tracks',
                        headers=headers,
                        params=params
                    ) as fallback_response:
                        if fallback_response.status != 200:
                            return None
                        data = await fallback_response.json()
                else:
                    data = await response.json()
                
                tracks = data.get('collection', data) if isinstance(data, dict) else data
                if not tracks:
                    return None
                
                # Find best match
                best_match = None
                best_score = 0.0
                
                for track in tracks:
                    track_title = track.get('title', '')
                    track_user = track.get('user', {}).get('username', '') if track.get('user') else ''
                    candidate = f"{track_title} {track_user}"
                    
                    score = self._calculate_match_score(query, candidate)
                    if score > best_score:
                        best_score = score
                        best_match = {
                            'id': str(track.get('id', '')),
                            'title': track_title,
                            'artist': track_user,
                            'match_score': score
                        }
                
                if best_match and best_score >= 0.5:
                    await self._cache_result(query, 'soundcloud', best_match)
                    return best_match
                
        except Exception as e:
            print(f"SoundCloud search error: {e}")
        
        return None

    async def batch_search_tracks(
        self, 
        session_id: str, 
        track_list: List[Tuple[str, str]], 
        platform: str,
        progress_callback: Optional[Callable] = None
    ) -> List[Optional[Dict]]:
        """Search multiple tracks in parallel with progress tracking"""
        
        semaphore = asyncio.Semaphore(5)  # Limit concurrent requests
        
        async def search_with_semaphore(index: int, title: str, artist: str):
            async with semaphore:
                if platform == 'spotify':
                    result = await self.search_spotify_track(session_id, title, artist)
                else:
                    result = await self.search_soundcloud_track(session_id, title, artist)
                
                if progress_callback:
                    progress_callback(index + 1, len(track_list), f"Searched: {title} - {artist}")
                
                return result
        
        tasks = [
            search_with_semaphore(i, title, artist) 
            for i, (title, artist) in enumerate(track_list)
        ]
        
        return await asyncio.gather(*tasks, return_exceptions=True)

# Usage example function
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