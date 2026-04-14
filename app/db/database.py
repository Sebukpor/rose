"""
Supabase Database Connection - SQLAlchemy with PostgreSQL
Manages connection to Supabase database
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages Supabase PostgreSQL connection"""
    
    def __init__(self, database_url: str):
        """
        Initialize database connection.
        
        Args:
            database_url: PostgreSQL connection string from Supabase
                         Format: postgresql://user:password@host:port/database
        """
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        self.database_url = database_url
        
        # Create engine with connection pooling
        self.engine = create_engine(
            database_url,
            # Disable connection pooling for serverless (HF Spaces)
            poolclass=NullPool,
            echo=False,
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=30000"  # 30 seconds
            }
        )
        
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
        
        logger.info("✅ Database connection pool initialized (NullPool for serverless)")
    
    def create_all_tables(self, base):
        """Create all tables from model definitions"""
        try:
            base.metadata.create_all(bind=self.engine)
            logger.info("✅ All database tables created/verified")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise
    
    def get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()
    
    def close(self):
        """Close connection pool"""
        self.engine.dispose()
        logger.info("✅ Database connections closed")


# Global instance
_db_manager = None


def init_db(database_url: str) -> DatabaseManager:
    """Initialize and return database manager"""
    global _db_manager
    _db_manager = DatabaseManager(database_url)
    return _db_manager


def get_db_manager() -> DatabaseManager:
    """Get database manager instance"""
    if _db_manager is None:
        raise RuntimeError("Database manager not initialized")
    return _db_manager


def get_db() -> Session:
    """Dependency for FastAPI to inject database session"""
    db = get_db_manager().get_session()
    try:
        yield db
    finally:
        db.close()
