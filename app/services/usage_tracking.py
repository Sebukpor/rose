"""
Usage Tracking Database Service - Tracks token consumption per user/session.
Provides SQLite storage for usage analytics and freemium tier enforcement.
"""
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """Represents a single token usage record"""
    user_id: str
    session_id: str
    endpoint: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    total_billable_tokens: int
    timestamp: datetime
    cache_hit: bool = False
    error: Optional[str] = None
    request_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "endpoint": self.endpoint,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "total_billable_tokens": self.total_billable_tokens,
            "timestamp": self.timestamp.isoformat(),
            "cache_hit": self.cache_hit,
            "error": self.error,
            "request_id": self.request_id
        }


@dataclass
class UsageStats:
    """Aggregated usage statistics for a user"""
    user_id: str
    total_tokens: int
    total_requests: int
    cached_tokens: int
    period_start: datetime
    period_end: datetime
    last_used: datetime
    
    @property
    def remaining_tokens(self) -> int:
        """Override this in FreemiumLimiter based on tier"""
        return -1  # Unlimited indicator
    
    @property
    def percentage_used(self) -> float:
        """Percentage of quota used (0-100)"""
        if self.limit <= 0:
            return 0
        return min(100, (self.total_tokens / self.limit) * 100)


class UsageDatabase:
    """SQLite backend for usage tracking"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"Usage database initialized at {db_path}")
    
    def _init_db(self):
        """Initialize database schema"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    total_billable_tokens INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    cache_hit BOOLEAN DEFAULT 0,
                    error TEXT,
                    request_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_timestamp 
                ON usage_records(user_id, timestamp DESC)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_id 
                ON usage_records(session_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_endpoint 
                ON usage_records(endpoint)
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_quotas (
                    user_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT 'free',
                    monthly_limit INTEGER NOT NULL,
                    billing_cycle_start TIMESTAMP NOT NULL,
                    billing_cycle_end TIMESTAMP NOT NULL,
                    tokens_used_this_cycle INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_tier 
                ON user_quotas(user_id, tier)
            """)
            
            # Monthly usage breakdown for analytics
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    total_tokens INTEGER DEFAULT 0,
                    total_requests INTEGER DEFAULT 0,
                    unique_sessions INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, year, month)
                )
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
    
    async def record_usage(self, record: UsageRecord) -> int:
        """Record a token usage event"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._record_usage_sync, record)
    
    def _record_usage_sync(self, record: UsageRecord) -> int:
        """Synchronous usage recording"""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO usage_records (
                    user_id, session_id, endpoint, input_tokens, output_tokens,
                    cached_tokens, total_billable_tokens, timestamp, cache_hit, error, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.user_id, record.session_id, record.endpoint,
                record.input_tokens, record.output_tokens,
                record.cached_tokens, record.total_billable_tokens,
                record.timestamp, record.cache_hit, record.error, record.request_id
            ))
            conn.commit()
            return cursor.lastrowid
    
    async def get_user_usage(self, user_id: str, days: int = 30) -> List[UsageRecord]:
        """Get usage records for a user in the last N days"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_user_usage_sync, user_id, days)
    
    def _get_user_usage_sync(self, user_id: str, days: int) -> List[UsageRecord]:
        """Synchronous user usage retrieval"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM usage_records 
                WHERE user_id = ? AND timestamp > ?
                ORDER BY timestamp DESC
            """, (user_id, cutoff.isoformat())).fetchall()
            
            return [self._row_to_record(row) for row in rows]
    
    async def get_monthly_usage(self, user_id: str, year: int, month: int) -> Dict[str, int]:
        """Get aggregated monthly usage"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_monthly_usage_sync, user_id, year, month)
    
    def _get_monthly_usage_sync(self, user_id: str, year: int, month: int) -> Dict[str, int]:
        """Sync monthly usage retrieval"""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT total_tokens, total_requests, unique_sessions 
                FROM monthly_usage 
                WHERE user_id = ? AND year = ? AND month = ?
            """, (user_id, year, month)).fetchone()
            
            if row:
                return dict(row)
            return {"total_tokens": 0, "total_requests": 0, "unique_sessions": 0}
    
    async def aggregate_daily_usage(self) -> None:
        """Aggregate daily usage into monthly buckets (run as background job)"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._aggregate_daily_usage_sync)
    
    def _aggregate_daily_usage_sync(self) -> None:
        """Synchronous daily aggregation"""
        with self._get_conn() as conn:
            # Get yesterday's data that hasn't been aggregated yet
            conn.execute("""
                INSERT OR REPLACE INTO monthly_usage (user_id, year, month, total_tokens, total_requests, unique_sessions)
                SELECT 
                    user_id,
                    CAST(strftime('%Y', timestamp) AS INTEGER),
                    CAST(strftime('%m', timestamp) AS INTEGER),
                    SUM(total_billable_tokens),
                    COUNT(*),
                    COUNT(DISTINCT session_id)
                FROM usage_records
                WHERE timestamp >= date('now', '-1 day') 
                    AND timestamp < date('now')
                GROUP BY user_id, year, month
            """)
            conn.commit()
            logger.info("Daily usage aggregation completed")
    
    async def get_user_stats(self, user_id: str) -> Optional[UsageStats]:
        """Get usage statistics for a user"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_user_stats_sync, user_id)
    
    def _get_user_stats_sync(self, user_id: str) -> Optional[UsageStats]:
        """Synchronous stats retrieval"""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT 
                    user_id,
                    SUM(total_billable_tokens) as total_tokens,
                    COUNT(*) as total_requests,
                    SUM(cached_tokens) as cached_tokens,
                    MIN(timestamp) as period_start,
                    MAX(timestamp) as period_end
                FROM usage_records
                WHERE user_id = ?
                GROUP BY user_id
            """, (user_id,)).fetchone()
            
            if not row:
                return None
            
            return UsageStats(
                user_id=row['user_id'],
                total_tokens=row['total_tokens'] or 0,
                total_requests=row['total_requests'] or 0,
                cached_tokens=row['cached_tokens'] or 0,
                period_start=datetime.fromisoformat(row['period_start']),
                period_end=datetime.fromisoformat(row['period_end'])
            )
    
    def _row_to_record(self, row: sqlite3.Row) -> UsageRecord:
        """Convert database row to UsageRecord"""
        return UsageRecord(
            user_id=row['user_id'],
            session_id=row['session_id'],
            endpoint=row['endpoint'],
            input_tokens=row['input_tokens'],
            output_tokens=row['output_tokens'],
            cached_tokens=row['cached_tokens'],
            total_billable_tokens=row['total_billable_tokens'],
            timestamp=datetime.fromisoformat(row['timestamp']),
            cache_hit=bool(row['cache_hit']),
            error=row['error'],
            request_id=row['request_id']
        )
    
    async def cleanup_old_records(self, days: int = 90) -> int:
        """Delete usage records older than N days"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._cleanup_old_records_sync, days)
    
    def _cleanup_old_records_sync(self, days: int) -> int:
        """Synchronous cleanup"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM usage_records WHERE timestamp < ?",
                (cutoff.isoformat(),)
            )
            conn.commit()
            logger.info(f"Cleaned up {cursor.rowcount} records older than {days} days")
            return cursor.rowcount
