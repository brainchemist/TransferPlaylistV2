# rate_limiting.py
import time
import json
import hashlib
from typing import Dict, Optional, Any
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import asyncio

@dataclass
class RateLimit:
    requests_per_minute: int
    requests_per_hour: int
    burst_limit: int = 10

# Platform-specific rate limits
RATE_LIMITS = {
    'spotify': RateLimit(requests_per_minute=100, requests_per_hour=1000, burst_limit=10),
    'soundcloud': RateLimit(requests_per_minute=60, requests_per_hour=500, burst_limit=5),
}

class RateLimiter:
    """Token bucket rate limiter with burst support"""
    
    def __init__(self):
        self.buckets: Dict[str, Dict] = defaultdict(lambda: {
            'tokens': 0,
            'last_refill': time.time(),
            'minute_requests': deque(),
            'hour_requests': deque()
        })
    
    def _clean_old_requests(self, requests_queue: deque, max_age: int):
        """Remove requests older than max_age seconds"""
        now = time.time()
        while requests_queue and now - requests_queue[0] > max_age:
            requests_queue.popleft()
    
    def can_make_request(self, platform: str, session_id: str) -> tuple[bool, Optional[int]]:
        """
        Check if a request can be made and return (allowed, wait_time)
        """
        key = f"{platform}:{session_id}"
        bucket = self.buckets[key]
        rate_limit = RATE_LIMITS.get(platform)
        
        if not rate_limit:
            return True, None
        
        now = time.time()
        
        # Clean old requests
        self._clean_old_requests(bucket['minute_requests'], 60)
        self._clean_old_requests(bucket['hour_requests'], 3600)
        
        # Check minute limit
        if len(bucket['minute_requests']) >= rate_limit.requests_per_minute:
            oldest_request = bucket['minute_requests'][0]
            wait_time = int(60 - (now - oldest_request) + 1)
            return False, wait_time
        
        # Check hour limit
        if len(bucket['hour_requests']) >= rate_limit.requests_per_hour:
            oldest_request = bucket['hour_requests'][0]
            wait_time = int(3600 - (now - oldest_request) + 1)
            return False, wait_time
        
        # Refill tokens for burst protection
        time_since_refill = now - bucket['last_refill']
        tokens_to_add = int(time_since_refill * rate_limit.requests_per_minute / 60)
        bucket['tokens'] = min(
            rate_limit.burst_limit,
            bucket['tokens'] + tokens_to_add
        )
        bucket['last_refill'] = now
        
        # Check burst limit
        if bucket['tokens'] < 1:
            return False, 1  # Wait 1 second for token refill
        
        return True, None
    
    def consume_request(self, platform: str, session_id: str):
        """Record that a request was made"""
        key = f"{platform}:{session_id}"
        bucket = self.buckets[key]
        now = time.time()
        
        bucket['minute_requests'].append(now)
        bucket['hour_requests'].append(now)
        bucket['tokens'] -= 1
    
    async def wait_if_needed(self, platform: str, session_id: str) -> bool:
        """Wait if rate limited, return True if wait was needed"""
        allowed, wait_time = self.can_make_request(platform, session_id)
        if not allowed and wait_time:
            await asyncio.sleep(wait_time)
            return True
        return False

class SearchCache:
    """In-memory cache for search results with TTL"""
    
    def __init__(self, max_size: int = 10000, default_ttl: int = 3600):
        self.cache: Dict[str, Dict] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl
    
    def _generate_key(self, query: str, platform: str) -> str:
        """Generate cache key from query and platform"""