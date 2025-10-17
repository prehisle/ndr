from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.common.config import get_settings

settings = get_settings()
engine = create_engine(settings.DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)