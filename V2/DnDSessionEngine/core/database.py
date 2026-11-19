from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.config import DATABASE_PATH
import sqlite3
import logging

logger = logging.getLogger(__name__)


def create_tables(conn):
    # MANIFEST
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manifest (
            entity_id INTEGER PRIMARY KEY,
            id INTEGER NOT NULL,
            name TEXT NOT NULL,
            module TEXT NOT NULL,
            type TEXT,
            summary TEXT
        )
    """)

    # CHARACTERS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            entity_id INTEGER PRIMARY KEY,
            id INTEGER NOT NULL,
            name TEXT NOT NULL,
            title TEXT,
            status_id INTEGER,
            entry TEXT,
            type TEXT,
            age TEXT,
            sex TEXT,
            aliases TEXT,
            families TEXT,
            locations TEXT,
            appearance TEXT,
            personality TEXT,
            FOREIGN KEY (entity_id) REFERENCES manifest(entity_id)
        )
    """)

    # LOCATIONS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            entity_id INTEGER PRIMARY KEY,
            id INTEGER NOT NULL,
            name TEXT NOT NULL,
            title TEXT,
            status_id INTEGER,
            parent_id INTEGER,
            entry TEXT,
            FOREIGN KEY (entity_id) REFERENCES manifest(entity_id)
        )
    """)


def initialise_database():
    logger.info("Initialising database...")
    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.execute("PRAGMA foreigh_keys = ON")
            create_tables(conn)
        logger.info("Initialising database, Done!")
    except Exception:
        logger.error("Failed to initilialise database!")
        raise
