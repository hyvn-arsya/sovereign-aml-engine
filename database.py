import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Database URL configuration
# We default to a local SQLite database file so you don't need Docker installed!
# When we deploy to AWS in Phase 6, we will pass the RDS PostgreSQL credentials here.
DB_HOST = os.getenv("DB_HOST")
if DB_HOST:
    # Construct postgresql URL for AWS RDS
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_NAME = os.getenv("DB_NAME", "sovereign")
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}"
else:
    DATABASE_URL = os.getenv(
        "DATABASE_URL", 
        "sqlite:///./sovereign_local.db"
    )

# 2. Engine Creation
# If using SQLite, we need a special flag for FastAPI multi-threading compatibility
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

# 3. SessionLocal class
# Each instance of the SessionLocal class will be a database session.
# We disable autocommit and autoflush so we can manage transactions manually.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. Declarative Base
# All our ORM models (classes) will inherit from this Base class.
# This is how SQLAlchemy knows which classes represent tables in the database.
Base = declarative_base()

# 5. Dependency for FastAPI
# This generator yields a database session for a single request,
# and ensures the session is closed when the request is done.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
