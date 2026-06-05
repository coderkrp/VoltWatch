from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .core.settings import DATABASE_URL

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_startup_migrations():
    """Schema migration is intentionally omitted for clean-slate deployments."""
    return
