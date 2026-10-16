import concurrent.futures

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def check_db_connection() -> bool:
    """Return True if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def check_db_ready(timeout_seconds: float | None = None) -> bool:
    """
    Return True if the database is reachable within *timeout_seconds*.

    Uses a background thread so the caller is not blocked indefinitely when
    the database is unreachable or slow to respond.

    Args:
        timeout_seconds: Maximum seconds to wait.  Defaults to the value
                         in settings.db_health_check_timeout_seconds.

    Returns:
        True  — database responded with SELECT 1 within the timeout.
        False — database unreachable, raised an exception, or timed out.
    """
    if timeout_seconds is None:
        timeout_seconds = settings.db_health_check_timeout_seconds

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(check_db_connection)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            return False
        except Exception:
            return False
