"""
Gemini Context Cache Manager with SQLite Persistent Storage for Hugging Face Spaces
Optimized for ephemeral storage environments with proper cleanup.
"""
import json
import logging
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import asyncio
from pathlib import Path
from app.core.config import get_settings
logger = logging.getLogger(__name__)
settings = get_settings()
@dataclass
class CacheEntry:
    """Represents a cached context entry"""
    cache_name: str # Gemini's cache resource name
    session_id: str # Unique session identifier
    model_name: str
    created_at: datetime
    expires_at: datetime
    token_count: int
    content_hash: str
    metadata: Dict[str, Any]
   
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at
   
    def time_until_expiry(self) -> timedelta:
        return self.expires_at - datetime.utcnow()
   
    def should_refresh(self, threshold_minutes: int = 10) -> bool:
        return self.time_until_expiry() < timedelta(minutes=threshold_minutes)
class SQLiteCacheBackend:
    """SQLite-based persistent cache storage for Hugging Face Spaces"""
   
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"SQLite cache backend initialized at {db_path}")
   
    def _init_db(self):
        """Initialize SQLite database with cache table"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gemini_cache (
                    session_id TEXT PRIMARY KEY,
                    cache_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    token_count INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at ON gemini_cache(expires_at)
            """)
            conn.commit()
   
    @contextmanager
    def _get_conn(self):
        """Get database connection with proper cleanup"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
   
    def _row_to_entry(self, row: sqlite3.Row) -> CacheEntry:
        return CacheEntry(
            cache_name=row['cache_name'],
            session_id=row['session_id'],
            model_name=row['model_name'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=datetime.fromisoformat(row['expires_at']),
            token_count=row['token_count'],
            content_hash=row['content_hash'],
            metadata=json.loads(row['metadata'])
        )
   
    async def get(self, session_id: str) -> Optional[CacheEntry]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_sync, session_id)
   
    def _get_sync(self, session_id: str) -> Optional[CacheEntry]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM gemini_cache WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            return self._row_to_entry(row) if row else None
   
    async def set(self, entry: CacheEntry) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._set_sync, entry)
   
    def _set_sync(self, entry: CacheEntry) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO gemini_cache
                (session_id, cache_name, model_name, created_at, expires_at, token_count, content_hash, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.session_id,
                entry.cache_name,
                entry.model_name,
                entry.created_at.isoformat(),
                entry.expires_at.isoformat(),
                entry.token_count,
                entry.content_hash,
                json.dumps(entry.metadata)
            ))
            conn.commit()
   
    async def delete(self, session_id: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._delete_sync, session_id)
   
    def _delete_sync(self, session_id: str) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM gemini_cache WHERE session_id = ?", (session_id,))
            conn.commit()
   
    async def list_all(self) -> List[CacheEntry]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._list_all_sync)
   
    def _list_all_sync(self) -> List[CacheEntry]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM gemini_cache").fetchall()
            return [self._row_to_entry(row) for row in rows]
   
    async def cleanup_expired(self) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._cleanup_expired_sync)
   
    def _cleanup_expired_sync(self) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM gemini_cache WHERE expires_at < ?",
                (datetime.utcnow().isoformat(),)
            )
            conn.commit()
            return cursor.rowcount
class GeminiCacheManager:
    """
    Manages Gemini context caching with SQLite persistent storage.
    Optimized for Hugging Face Spaces ephemeral environment.
    """
   
    def __init__(self):
        self.settings = get_settings()
        self._backend = SQLiteCacheBackend(self.settings.GEMINI_CACHE_DB_PATH)
        self._client = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._refresh_locks: Dict[str, asyncio.Lock] = {}
        self._shutdown = False
   
    def set_client(self, client):
        """Set the Gemini client"""
        self._client = client
   
    async def start(self):
        """Start background cleanup task"""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        # Run initial cleanup
        await self._backend.cleanup_expired()
        logger.info("GeminiCacheManager started with SQLite backend")
   
    async def stop(self):
        """Stop background tasks and cleanup"""
        self._shutdown = True
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
       
        # Cleanup Gemini API caches on shutdown
        if self._client:
            try:
                entries = await self._backend.list_all()
                for entry in entries:
                    try:
                        await self._client.aio.caches.delete(name=entry.cache_name)
                        logger.info(f"Deleted cache {entry.cache_name}")
                    except Exception as e:
                        logger.debug(f"Cache {entry.cache_name} already deleted or error: {e}")
            except Exception as e:
                logger.warning(f"Error during cache cleanup: {e}")
       
        logger.info("GeminiCacheManager stopped")
   
    async def _periodic_cleanup(self):
        """Periodically clean up expired cache entries"""
        while not self._shutdown:
            try:
                await asyncio.sleep(300) # Every 5 minutes
                if self._shutdown:
                    break
                count = await self._backend.cleanup_expired()
                if count > 0:
                    logger.info(f"Cleaned up {count} expired cache entries")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}")
   
    def _generate_session_id(self, system_prompt: str, model_name: str) -> str:
        """Generate unique session ID"""
        content = f"{model_name}:{system_prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]
   
    def _compute_content_hash(self, system_prompt: str) -> str:
        """Compute hash of cached content"""
        return hashlib.sha256(system_prompt.encode()).hexdigest()
   
    async def get_or_create_cache(
        self,
        system_prompt: str,
        model_name: str,
        ttl: Optional[timedelta] = None
    ) -> tuple[str, bool]:
        """
        Get existing cache or create new one.
        Returns (cache_name, is_new)
        """
        if not self.settings.GEMINI_CACHE_ENABLED or not self._client:
            return None, False
       
        session_id = self._generate_session_id(system_prompt, model_name)
        content_hash = self._compute_content_hash(system_prompt)
       
        # Check existing cache
        existing = await self._backend.get(session_id)
        if existing:
            if existing.content_hash != content_hash:
                logger.info(f"Content changed, recreating cache for {session_id[:8]}...")
                await self._invalidate_cache(existing)
            elif existing.should_refresh():
                logger.info(f"Refreshing cache for {session_id[:8]}...")
                await self._refresh_cache(existing, system_prompt, ttl)
                return existing.cache_name, False
            else:
                logger.debug(f"Using existing cache for {session_id[:8]}")
                return existing.cache_name, False
       
        # Create new cache
        return await self._create_new_cache(session_id, system_prompt, model_name, content_hash, ttl)
   
    async def _create_new_cache(
        self,
        session_id: str,
        system_prompt: str,
        model_name: str,
        content_hash: str,
        ttl: Optional[timedelta]
    ) -> tuple[str, bool]:
        """Create new cache in Gemini API"""
        try:
            from google.genai import types
           
            # Convert timedelta to seconds string format required by API
            cache_ttl = ttl or self.settings.gemini_cache_ttl
            ttl_seconds = int(cache_ttl.total_seconds())
            ttl_string = f"{ttl_seconds}s" # API expects "3600s" format
           
            # Create cached content
            cache = await self._client.aio.caches.create(
                model=model_name,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_prompt,
                    ttl=ttl_string # Fixed: pass as string, not timedelta
                )
            )
           
            # Estimate token count (rough approximation)
            token_count = len(system_prompt.split()) * 1.3
           
            entry = CacheEntry(
                cache_name=cache.name,
                session_id=session_id,
                model_name=model_name,
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + cache_ttl,
                token_count=int(token_count),
                content_hash=content_hash,
                metadata={
                    "system_prompt_length": len(system_prompt),
                    "ttl_minutes": cache_ttl.total_seconds() / 60
                }
            )
           
            await self._backend.set(entry)
            logger.info(f"Created new cache {cache.name[:30]}... for {session_id[:8]}")
            return cache.name, True
           
        except Exception as e:
            logger.error(f"Failed to create cache: {e}")
            return None, False
   
    async def _refresh_cache(
        self,
        entry: CacheEntry,
        system_prompt: str,
        ttl: Optional[timedelta]
    ):
        """Refresh cache TTL before expiry"""
        if entry.session_id not in self._refresh_locks:
            self._refresh_locks[entry.session_id] = asyncio.Lock()
       
        async with self._refresh_locks[entry.session_id]:
            try:
                new_ttl = ttl or self.settings.gemini_cache_ttl
                ttl_seconds = int(new_ttl.total_seconds())
                ttl_string = f"{ttl_seconds}s" # Fixed: pass as string
               
                # Update TTL in Gemini API
                await self._client.aio.caches.update(
                    name=entry.cache_name,
                    config={"ttl": ttl_string} # Fixed: pass as string
                )
               
                # Update local record
                entry.expires_at = datetime.utcnow() + new_ttl
                await self._backend.set(entry)
                logger.info(f"Refreshed cache {entry.cache_name[:30]}...")
               
            except Exception as e:
                logger.error(f"Failed to refresh cache: {e}")
   
    async def _invalidate_cache(self, entry: CacheEntry):
        """Invalidate and delete cache entry"""
        try:
            await self._client.aio.caches.delete(name=entry.cache_name)
        except Exception as e:
            logger.debug(f"Cache {entry.cache_name} already deleted: {e}")
        finally:
            await self._backend.delete(entry.session_id)
   
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        entries = await self._backend.list_all()
        total_entries = len(entries)
        active_entries = sum(1 for e in entries if not e.is_expired())
        total_tokens = sum(e.token_count for e in entries)
       
        # Calculate estimated savings (rough estimate)
        # Cached tokens cost ~1/4 of input tokens
        estimated_savings = total_tokens * 0.75 * active_entries if active_entries > 0 else 0
       
        return {
            "total_entries": total_entries,
            "active_entries": active_entries,
            "expired_entries": total_entries - active_entries,
            "estimated_cached_tokens": int(total_tokens),
            "estimated_cost_savings": f"{estimated_savings:,.0f} tokens",
            "backend_type": "SQLite",
            "db_path": self.settings.GEMINI_CACHE_DB_PATH
        }
# Global singleton instance
_cache_manager: Optional[GeminiCacheManager] = None
async def get_cache_manager() -> GeminiCacheManager:
    """Get or create the singleton cache manager"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = GeminiCacheManager()
        await _cache_manager.start()
    return _cache_manager