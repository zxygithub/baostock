"""Database initialization script for BaoStock data project."""

import sys
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DB_PATH
from src.db_manager import DBManager


def main() -> None:
    try:
        with DBManager(str(DB_PATH)) as db:
            db.init_all_tables()
        print(f"Database initialized at {DB_PATH}")
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
