from database import engine, Base
import models
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("init_db")

def init_database():
    log.info("Creating database tables...")
    # This will create the tables in the local SQLite file
    Base.metadata.create_all(bind=engine)
    log.info("Tables created successfully!")

if __name__ == "__main__":
    init_database()
